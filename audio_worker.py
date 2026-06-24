import queue
import time
import numpy as np
import torch
import librosa
import sounddevice as sd
from collections import deque, Counter
from PyQt6.QtCore import QThread, pyqtSignal
from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForSequenceClassification

class AudioWorker(QThread):
    audio_data_signal=pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.running = True
        # Uses FeatureExtractor
        self.processor = Wav2Vec2FeatureExtractor.from_pretrained("superb/wav2vec2-base-superb-er")

        # Uses ForSequenceClassification to get actual emotion labels
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = Wav2Vec2ForSequenceClassification.from_pretrained("superb/wav2vec2-base-superb-er").to(self.device)

        self.MIC_RATE=48000
        self.SAMPLE_RATE = 16000
        self.DURATION = 3  # seconds

        self.noise_floor_rms = 0.001
        self.neutral_pitch_base = 120.0
        self.calib_pitch_std = 20.0
        self.baseline_emotion = "neu"
        self.calib_volume = 0.0

        # This stores the last 3 predictions to stop the jumping
        self.emotion_buffer = deque(maxlen=3)
        self.confidence_buffer = deque(maxlen=3)

        # AUDIO CALIBRATION 
        self.calib_phase = 0
        self.noise_floor_rms = 0.0
        self.neutral_pitch_base = 0.0
        self.calib_pitch_std = 0.0
        self.CALIB_PHASE_DURATION = 6.0  # 6s for room, 6s for voice


    def run(self):
        audio_q = queue.Queue()
        MAX_SAMPLES = self.SAMPLE_RATE * self.DURATION 
        conveyor_belt = np.zeros(MAX_SAMPLES, dtype=np.float32)
        def audio_callback(indata, frames, time, status):
            try:
                # Check if there are getting 2 channels
                if indata.shape[1] > 1:
                    # Take only the first channel [:, 0] and keep the shape correct
                    data_to_process = indata[:, 0].reshape(-1, 1)
                else:
                    data_to_process = indata

                #put_nowait ensures the audio driver never has to wait for your code    
                # Put the cleaned mono data into the queue
                audio_q.put_nowait(data_to_process.copy())

            except queue.Full:
                pass # If full, just drop the frame to prevent the overflow error
            

        while self.running:
            # This looks for a device with 'Microphone' in the name that ISN'T the 'Array' (Laptop mic)
            target_id = None
            # Get the default input device
            default_input = sd.default.device[0]  # index of default input device
            devices = sd.query_devices()

            if default_input is not None and default_input >= 0:
                target_id = default_input
                print("Default microphone:", devices[target_id]['name'])
            else:
                print("No default input device found")

            # Starts audio stream from microphone. It always runs and never stops
            with sd.InputStream(device=target_id, samplerate=self.MIC_RATE, channels=2, callback=audio_callback, blocksize=16384):
                # Flush the queue ONCE before starting the main loop
                while not audio_q.empty():
                    audio_q.get()
                    audio_q.task_done()

                while self.running:
                    raw_slices = []
                    while not audio_q.empty():
                        # Just grab raw data as fast as possible
                        raw_slices.append(audio_q.get().flatten())
                        audio_q.task_done()

                    if raw_slices:
                        # Combine all small slices into one bigger block
                        combined_raw = np.concatenate(raw_slices)
                        new_data_16k = combined_raw[::3]
            
                        # Now slide the belt
                        shift = len(new_data_16k)
                        # If new data is bigger than the belt, just take the last 48000 samples
                        if shift > MAX_SAMPLES:
                            conveyor_belt[:] = new_data_16k[-MAX_SAMPLES:]
                        else:
                            conveyor_belt = np.roll(conveyor_belt, -shift)
                            conveyor_belt[-shift:] = new_data_16k

                    # Calibration
                    if self.calib_phase == 1:
                        # CALIBRATING PHASE 1: Stay SILENT
                        # bucket is used as no sample should be discarded during those 5 seconds
                        raw_room_bucket = [] 
                        start_time = time.time()
                        while time.time() - start_time < self.CALIB_PHASE_DURATION:
                            while not audio_q.empty():
                            # Just grab raw data - NO resampling here
                                raw_room_bucket.append(audio_q.get().flatten())
                            time.sleep(0.05)
        
                        # Combine and resample ONCE
                        if raw_room_bucket:
                            all_silence_16k = np.concatenate(raw_room_bucket)
                            self.noise_floor_rms = np.sqrt(np.mean(all_silence_16k**2))
                        else:
                            self.noise_floor_rms = 0.001
                        
                        self.calib_phase = 2
                        self.audio_data_signal.emit({"status": "PHASE_2_START"})

                    elif self.calib_phase == 2:
                        # CALIBRATING PHASE 2: Speak NATURALLY 
                        raw_voice_bucket = []
                        start_time = time.time()
                        while time.time() - start_time < self.CALIB_PHASE_DURATION:
                            while not audio_q.empty():
                                raw_voice_bucket.append(audio_q.get().flatten())
                            time.sleep(0.05)
            
                        if raw_voice_bucket:
                            voice_samples = np.concatenate(raw_voice_bucket)
                        else:
                            voice_samples = np.zeros(self.SAMPLE_RATE * int(self.CALIB_PHASE_DURATION)) # if no audio collected, zero array formed to prevent crashes
            
                        # Extract Pitch Baseline
                        pitches, mags = librosa.piptrack(y=voice_samples, sr=self.SAMPLE_RATE, fmin=75, fmax=400)
                        p_vals = []
                        for t in range(pitches.shape[1]):
                            idx = mags[:, t].argmax()
                            p = pitches[idx, t]
                            if p > 0: p_vals.append(p)
            
                        if p_vals:
                            self.neutral_pitch_base = np.mean(p_vals)
                            self.calib_pitch_std = np.std(p_vals)

                        else:
                            # FALLBACK: If no pitch is found, use a standard human default
                            self.neutral_pitch_base = 120.0 
                            self.calib_pitch_std = 20.0
                        
                        inputs_calib = self.processor(voice_samples, sampling_rate=self.SAMPLE_RATE, return_tensors="pt", padding=True, do_normalize=True)
                        inputs_calib = {k: v.to(self.device) for k, v in inputs_calib.items()}
                        with torch.no_grad():
                            outputs_calib = self.model(**inputs_calib)
        
                        self.calib_volume = np.sqrt(np.mean(voice_samples**2))
    
                        calib_logits = outputs_calib.logits
                        calib_pred_id = torch.argmax(calib_logits, dim=-1).item()
                        calib_label = self.model.config.id2label[calib_pred_id]

                        # Store this as the 'Baseline Emotion'
                        self.baseline_emotion = calib_label

                        #flush the queue so live detection starts fresh
                        while not audio_q.empty(): 
                            audio_q.get()
        
                        self.calib_phase = 0
                        #CALIBRATION COMPLETE
                        self.audio_data_signal.emit({"status": "CALIB_COMPLETE"})
                        continue


                    # Instead of recording, we just look at the 'conveyor_belt'
                    audio_norm = conveyor_belt.copy()

                    current_rms = np.sqrt(np.mean(audio_norm**2))
        
                    # If the sound is less than 4.0x the noise floor, it's just room noise
                    if current_rms < (self.noise_floor_rms * 4.0):
                        self.audio_data_signal.emit({
                        "emotion": "No audio detected"
                        })
                        time.sleep(0.2) # Prevent rapid-fire empty signals
                        continue

                    # PRE-PROCESSING for high accuracy
                    # Trim silence from speech
                    audio_trimmed, _ = librosa.effects.trim(audio_norm, top_db=35)
        
                    # Skip if the remaining speech is too short (less than 0.6s)
                    if len(audio_trimmed) < 10000:
                        continue

                    # Peak Normalization (Crucial for Wav2Vec accuracy)
                    audio_norm = audio_trimmed / (np.max(np.abs(audio_trimmed)) + 1e-9) # every audio is within a consistent range
                    audio_norm = audio_norm * 0.8  # Keep it at 80% volume so it doesn't sound "harsh"

                    inputs = self.processor(
                    audio_norm,
                    sampling_rate=self.SAMPLE_RATE,
                    return_tensors="pt", # converts array to pytorch tensors
                    padding=True, # all audio clips of same length
                    do_normalize=True,
                    return_attention_mask=True, # to differentiate between real audio and padding
                    )

                    current_volume = np.sqrt(np.mean(audio_norm**2))
    
                    inputs = {k: v.to(self.device) for k, v in inputs.items()}
                    with torch.no_grad():
                        outputs = self.model(**inputs)

                    logits = outputs.logits # logits are raw predictions(internal scores of each emotion)
                    probabilities = torch.nn.functional.softmax(logits, dim=-1)
                    confidence, predicted_id = torch.max(probabilities, dim=-1) 
                    predicted_id = predicted_id.item() # picks the id of most likely emotion

                    if confidence.item() < 0.40:
                        self.audio_data_signal.emit({
                        "emotion": "Speech detected,but emotion unclear"
                        })
                        continue

                    emotion = self.model.config.id2label[predicted_id] # converts the predicted id to corresponding emotion label
                    conf = confidence.item()

                    if emotion == self.baseline_emotion:
                        emotion = "neu"
                    else:
                        emotion = emotion

                    if self.baseline_emotion == "ang":
                    # If they sound "Angry" but they are 2.5x louder than their calibration...
                        if current_volume > (self.calib_volume * 2.5):
                            emotion = "ang" # This is TRUE anger
                        else:
                            emotion = "neu" 

                    if self.baseline_emotion == "sad": 
                        # Check if the voice has become even more monotone than the baseline
                        pitches, mags = librosa.piptrack(y=audio_norm, sr=self.SAMPLE_RATE)
                        p_vals = [pitches[mags[:, t].argmax(), t] for t in range(pitches.shape[1]) if pitches[mags[:, t].argmax(), t] > 0]
    
                        if p_vals:
                            current_std = np.std(p_vals)
                            # If their pitch variance drops by another 40%, it's "True Sadness"
                            if current_std < (self.calib_pitch_std * 0.6): 
                                emotion = "sad" # Override the "neutral" and report real distress

                    self.emotion_buffer.append(emotion)
                    self.confidence_buffer.append(conf)

                    # Pick the most frequent emotion in the buffer
                    counts = Counter(self.emotion_buffer)
                    stable_emotion = counts.most_common(1)[0][0]
                    avg_conf = sum(self.confidence_buffer)/len(self.confidence_buffer)

                    self.audio_data_signal.emit({
                    "emotion": stable_emotion,
                    "waveform": conveyor_belt[::10]
                    })

                    time.sleep(0.4)

    def stop(self):
        self.running = False