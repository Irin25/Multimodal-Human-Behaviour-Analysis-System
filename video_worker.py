import cv2
import time
import threading
import numpy as np
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal
from deepface import DeepFace
from retinaface import RetinaFace
import tensorflow as tf

# GPU SETUP
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu, True)
    print("Hardware Acceleration Active")

class VideoWorker(QThread):
    image_signal=pyqtSignal(np.ndarray)
    data_signal=pyqtSignal(dict)

    def __init__(self): # for initialization of variables
        super().__init__() # makes VideoWorker run from parent class too(QThread)

        self.running=True
        self.cap=cv2.VideoCapture(0)
        self.emotion_window = deque(maxlen=5) # rolling window (takes 5 frames)
        self.display_emotion = None
        self.frame_count = 0
        self.prev_time = time.time()
        self.fps = 0

        self.smoothed_confidence = {}  # store EMA per emotion(Exponential Moving Average)
        self.avg_confidence = 0
        self.alpha = 0.2
        self.MIN_CONFIDENCE = 7  # below this, ignore emotion

        self.current_fa = None
        self.current_emotion = None
        self.stable_emotion = None # the emotion that is currently in display
        self.pending_emotion = None  # the emotion that will replace in the future
        self.pending_count = 0
        self.threshold = 2  # requires 2 consecutive frames before switching
        self.last_bbox = None

        #Gaze direction
        self.gaze_status="UNKNOWN"
        self.gaze_val=0

        # EAR(Eye Aspect Ratio)
        self.MAX_BLINK_FRAMES = 20  # maximum frames allowed for a blink
        self.ear_history = deque(maxlen=50)  # Stores the last 50 EAR values to know what "normal" is
        self.avg_ear=0
        self.blink_counter = 0
        self.blink_total = 0
        self.blink_start_time = time.time()
        self.blink_rate = 0
        self.eye_closed_frames = 0
        self.ear=0

        # Head pose and Calibration
        self.neutral_baselines = {} 
        self.emotion_samples = []
        self.pose_history = deque(maxlen=20)
        self.yaw = self.pitch = self.roll = 0
        self.head_status = "UNKNOWN"

        self.calibrated = False
        self.calib_phase = 0  # 0: Idle, 1: Sync (Room/Head), 2: Voice
        self.calib_start_time = None
        
        self.yaw_samples = []
        self.pitch_samples = []
        self.roll_samples = []

        self.yaw_offset = 0.0
        self.pitch_offset = 0.0
        self.roll_offset = 0.0

        # Creating a sub thread to handle ai processing seperately
        # maxlen=1 means it only ever keeps the newest frame
        self.frame_buffer = deque(maxlen=1)
        self.lock = threading.Lock() # mutex lock

        self.ai_thread = threading.Thread(target=self.ai_loop, daemon=True) # daemon means thread automatically stops when program exits
        self.ai_thread.start()

    def run(self): # running the VideoWorker thread
        # PRODUCER: Grabs frames and shows them instantly
        while self.running:
            ret, frame = self.cap.read() # reads the frame
            if not ret: # if there is no frame(ret stores boolean values)
                continue

            # Calculate fps
            current_time = time.time()              # Get the current time in seconds
            delta = current_time - self.prev_time   # Calculate how much time has passed since the last frame
            self.fps = 1 / delta if delta > 0 else 0  # FPS = 1 / time per frame (avoid division by zero)
            self.prev_time = current_time           # Update prev_time for the next calculation

            frame = cv2.flip(frame, 1) # makes the webcam behave like a mirror

            if self.current_fa is not None:
                # Scale coordinates: processing was at 320x240, display is full resolution
                scale_x = frame.shape[1] / 320
                scale_y = frame.shape[0] / 240
                
                x1 = int(self.current_fa[0] * scale_x)
                y1 = int(self.current_fa[1] * scale_y)
                x2 = int(self.current_fa[2] * scale_x)
                y2 = int(self.current_fa[3] * scale_y)
                
                # Color: Light Green (144, 238, 144 in BGR), Thickness: 1
                cv2.rectangle(frame, (x1, y1), (x2, y2), (144, 238, 144), 1)

            with self.lock:
                # This automatically overwrites the old frame with the new one
                self.frame_buffer.append(frame.copy())

            self.image_signal.emit(frame) # sends the current frame to the GUI for display

            time.sleep(0.01) # stabilize CPU

    def ai_loop(self): 
        # CONSUMER: Processes the queue as fast as the hardware allows
        while self.running:
            # Check if there is a frame to process
            if not self.frame_buffer:
                time.sleep(0.01)
                continue

            with self.lock:
                # .pop() takes the frame out so we don't process it twice
                frame = self.frame_buffer.pop()

            small_frame = cv2.resize(frame, (320, 240)) # smaller images means faster processing

            try:
                faces = RetinaFace.detect_faces(small_frame)

                # Check if we actually found faces
                if isinstance(faces, dict) and len(faces) > 0:
                    # Find the face with the largest bounding box area
                    largest_face = max(
                        faces.values(),
                        key=lambda f: (f['facial_area'][2] - f['facial_area'][0]) *
                                    (f['facial_area'][3] - f['facial_area'][1])
                    )

                    fa = largest_face['facial_area']  # [x1, y1, x2, y2]
                    landmarks = largest_face['landmarks']

                    self.current_fa = fa

                    # CROP THE FACE FOR DEEPFACE
                    x1, y1, x2, y2 = map(int, fa)

                    # Add a small buffer so the crop isn't too tight
                    margin = 20
                    crop_y1, crop_y2 = max(0, y1 - margin), min(240, y2 + margin)
                    crop_x1, crop_x2 = max(0, x1 - margin), min(320, x2 + margin)

                    cropped_face = small_frame[crop_y1:crop_y2, crop_x1:crop_x2]

                    if cropped_face.shape[0] < 50 or cropped_face.shape[1] < 50:
                        continue

                    result = DeepFace.analyze(cropped_face, actions=['emotion'],
                                    enforce_detection=True, detector_backend='skip')
                    
                    main_face = result[0]
                    raw_emotions = main_face['emotion']        
                    region = main_face['region'] # bounding box coordinates of face

                    self.head_status = "UNKNOWN" 
                    self.yaw, self.pitch, self.roll = 0, 0, 0
                    self.gaze_status, self.gaze_val = "UNKNOWN", 0
                    self.ear=0
                    
                    face_width = 320
                    face_height= 240
                
                    """Uses SolvePnP to estimate head pose from 2D landmarks."""
                    # 3D model points of a generic face
                    model_points = np.array([
                    (0.0, 0.0, 0.0),             # Nose tip
                    (0.0, -330.0, -65.0),        # Chin
                    (-225.0, 170.0, -135.0),     # Left eye
                    (225.0, 170.0, -135.0),      # Right eye
                    (-150.0, -150.0, -125.0),    # Left mouth corner
                    (150.0, -150.0, -125.0)      # Right mouth corner
                    ], dtype=np.float32)

                    # 2D points from RetinaFace (mapping nose, eyes, mouth)
                    # RetinaFace doesn't provide chin, so we estimate it relative to the nose and mouth
                    nose = np.array(landmarks['nose'])
                    left_eye = np.array(landmarks['left_eye'])
                    right_eye = np.array(landmarks['right_eye'])
                    mouth_left = np.array(landmarks['mouth_left'])
                    mouth_right = np.array(landmarks['mouth_right'])

                    # Estimating chin point
                    mouth_center_y = (mouth_left[1] + mouth_right[1]) / 2
                    nose_mouth_dist = mouth_center_y - nose[1]
                    chin_x, chin_y = nose[0], mouth_center_y + nose_mouth_dist

                    face_points = np.array([
                    nose,
                    (chin_x, chin_y),
                    left_eye,
                    right_eye,
                    mouth_left,
                    mouth_right
                    ], dtype=np.float32)

                    # Camera internals to correctly map between 3d head model and 2d image
                    focal_length = face_width
                    center = (face_width / 2, face_height / 2)
                    camera_matrix = np.array([
                    [focal_length, 0, center[0]],
                    [0, focal_length, center[1]],
                    [0, 0, 1]
                    ], dtype=np.float32)

                    dist_coeffs = np.zeros((4, 1)) # Assuming no distortion(pretending lens is perfect and there is no bending)

                    success, rot_vec, trans_vec = cv2.solvePnP(model_points, face_points, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE)
                    # rot_vec-rotation vector(how the head is rotated in 3d)
                    # trans_vec-where the head is in space
                    if not success:
                        self.yaw = self.pitch = self.roll = 0

                    # Convert rotation vector to Euler angles
                    rmat, _ = cv2.Rodrigues(rot_vec)
                    proj_matrix = np.hstack((rmat, trans_vec))
                    _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(proj_matrix)

                    # decomposeProjectionMatrix returns angles in a specific way; we extract and scale
                    p, y, r = euler_angles.flatten()

                    # Adjust axes for intuitive display
                    self.pitch = -p # Up/Down (Here you flip the sign of pitch so looking up gives positive values)
                    self.yaw = y    # Left/Right
                    self.roll = r   # Tilt

                    # --- UNIFIED CALIBRATION PHASE 1 ---
                    if self.calib_phase == 1:
                        if self.calib_start_time is None: self.calib_start_time = time.time()
                        self.yaw_samples.append(self.yaw)
                        self.pitch_samples.append(self.pitch)
                        self.roll_samples.append(self.roll)
                        self.emotion_samples.append(raw_emotions)

                        if time.time() - self.calib_start_time >= 6.0:
                            self.yaw_offset, self.pitch_offset, self.roll_offset = np.mean(self.yaw_samples), np.mean(self.pitch_samples), np.mean(self.roll_samples)
                            for emo in raw_emotions.keys():
                                self.neutral_baselines[emo] = np.mean([s[emo] for s in self.emotion_samples])
                            self.calibrated = True
                            self.calib_phase = 0
                            self.calib_start_time = None

                    
                    display_emotion = None
                    avg_confidence = 0

                    if self.calibrated:

                        # We subtract only 60% of the baseline so we don't kill the emotion entirely
                        adjusted_emotions = {emo: max(0, score - (self.neutral_baselines.get(emo, 0)*0.6)) for emo, score in raw_emotions.items()}
                        
                        # Apply Neutral Dead-Zone
                        if max(adjusted_emotions.values()) < 1.0 :
                            emotion = "neutral"
                        else:
                            emotion = max(adjusted_emotions, key=adjusted_emotions.get)
                        
                        confidence = raw_emotions.get(emotion, 0)
                        if confidence < self.MIN_CONFIDENCE: 
                            emotion = "neutral"
                            confidence = raw_emotions.get("neutral", 0)

                        # Stability & Majority Vote
                        self.emotion_window.append(emotion)
                        maj_emo = max(set(self.emotion_window), key=self.emotion_window.count)

                        if maj_emo != self.stable_emotion:
                            if maj_emo == self.pending_emotion: self.pending_count += 1
                            else: self.pending_emotion, self.pending_count = maj_emo, 1
                            if self.pending_count >= self.threshold: self.stable_emotion = self.pending_emotion
                        else:
                            self.pending_emotion, self.pending_count = None, 0
                        
                        self.current_emotion = self.stable_emotion if self.stable_emotion else emotion

                        # EMA Smoothing
                        if self.current_emotion not in self.smoothed_confidence:
                            self.smoothed_confidence[self.current_emotion] = confidence
                        else:
                            self.smoothed_confidence[self.current_emotion] = (self.alpha * confidence + (1 - self.alpha) * self.smoothed_confidence[self.current_emotion])
                        
                        avg_confidence = self.smoothed_confidence[self.current_emotion]
                        display_emotion = self.current_emotion
                        self.yaw -= self.yaw_offset
                        self.pitch -= self.pitch_offset
                        self.roll -= self.roll_offset

                        self.head_status = []

                        if self.yaw > 20:
                            self.head_status.append("HEAD LEFT")
                        elif self.yaw < -20:
                            self.head_status.append("HEAD RIGHT")

                        if self.pitch > 7:
                            self.head_status.append("HEAD UP")
                        elif self.pitch < -7:
                            self.head_status.append("HEAD DOWN")

                        if abs(self.roll) > 15:
                            self.head_status.append("HEAD TILTED")

                        if not self.head_status:
                            self.head_status.append("HEAD NEUTRAL")

                        self.head_status = ", ".join(self.head_status)
    

                    """uses centroid to estimate gaze"""
                    gaze_desc = "CENTER" # default
                    offsets = []

                    scale_x = frame.shape[1] / 320
                    scale_y = frame.shape[0] / 240

                    # Process both eyes
                    for eye_label in ['left_eye', 'right_eye']:
                        ex, ey = int(landmarks[eye_label][0] * scale_x), int(landmarks[eye_label][1] * scale_y)
    
                        # Crop a small area around the eye
                        w_margin, h_margin = 20, 12
                        eye_roi = frame[max(0, ey-h_margin):min(frame.shape[0], ey+h_margin), 
                        max(0, ex-w_margin):min(frame.shape[1], ex+w_margin)] # prevents going outside the image boundaries
    
                        if eye_roi.size == 0: continue

                        # Convert to gray and sharpen the contrast
                        gray_eye = cv2.cvtColor(eye_roi, cv2.COLOR_BGR2GRAY)
                        gray_eye = cv2.equalizeHist(gray_eye) 
                        gray_eye = cv2.GaussianBlur(gray_eye, (7, 7), 0)

                        # Logic: Find the darkest point and create a mask around it
                        min_val, _, _, _ = cv2.minMaxLoc(gray_eye)
                        _, iris_mask = cv2.threshold(gray_eye, min_val + 10, 255, cv2.THRESH_BINARY_INV)

                        M = cv2.moments(iris_mask)
                        if M['m00'] != 0:
                            cx = int(M['m10'] / M['m00'])
                            # Normalize to [-1.0, 1.0]
                            relative_x = (cx - (eye_roi.shape[1] / 2)) / (eye_roi.shape[1] / 2)
                            offsets.append(relative_x)

                    if offsets:
                        avg_offset = np.mean(offsets)
    
                        if avg_offset < -0.18: 
                            gaze_desc = "GAZE LEFT"
                        elif avg_offset > 0.18: 
                            gaze_desc = "GAZE RIGHT"
                        else:
                            gaze_desc = "CENTER"
        
                    else:
                        gaze_desc = "UNKNOWN"
                        self.gaze_val = 0
                    
                    self.gaze_status = gaze_desc

                    """Ear aspect ratio for blink detection"""
                    # retina face doesnt have 6 eye points, so it calculates an approximation
                    left_eye = np.array(landmarks['left_eye'])
                    right_eye = np.array(landmarks['right_eye'])

                    eye_width = np.linalg.norm(left_eye - right_eye) # gives horizontal distance across the eyes

                    # simulate vertical eye openness using nose-eye distance
                    nose = np.array(landmarks['nose'])
                    eye_height = abs(nose[1] - ((left_eye[1] + right_eye[1]) / 2))

                    ear = eye_height / eye_width

                    #eye aspect ratio for blink frequency using rolling average delta
                    self.ear_history.append(ear)

                    # Calculate the average "Eyes Open" value
                    if len(self.ear_history) > 10:
                        avg_ear = np.mean(self.ear_history)

                        # Detect a "Dip" (If current EAR is 5% lower than average)
                        if ear < (avg_ear * 0.95): 
                            self.eye_closed_frames += 1
                        else:
                        # eye just opened again
                            if 1 <= self.eye_closed_frames <= self.MAX_BLINK_FRAMES:
                                #    count as a blink only if closure was short
                                self.blink_total += 1
                                # reset counter
                                self.eye_closed_frames = 0
                    # Blink rate (per minute)
                    elapsed = time.time() - self.blink_start_time
                    if elapsed >= 10:
                        self.blink_rate = int((self.blink_total / elapsed) * 60)
                        self.blink_start_time = time.time()   # reset the window
                        self.blink_total = 0   

                    # Emit results to UI(backend to frontend)
                    self.data_signal.emit({
                        "emotion": display_emotion,
                        "confidence": avg_confidence,
                        "head_status": self.head_status,
                        "gaze_position": self.gaze_status,
                        "blink_rate": self.blink_rate
                    })

                else:
                    self.current_fa = None
                    self.data_signal.emit({
                    "emotion": "NO FACE DETECTED",
                    "confidence": 0,
                    "head_status": "NONE",
                    "gaze_position": "NONE",
                    "blink_rate": 0
                })

            except Exception as e:
                print(f"AI Error: {e}")
            

    def stop(self):
            self.running = False
            if self.ai_thread.is_alive():
                self.ai_thread.join(timeout=1)
            self.cap.release()

