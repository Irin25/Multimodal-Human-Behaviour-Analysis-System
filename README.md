# MHBAS

## Multimodal Human Behaviour Analysis System.

Real-time stress · attention · emotion analysis using webcam +
microphone --- no wearables, no cloud.

**Tech Stack:** Python 3.10+ · PyQt6 · PyTorch · TensorFlow · OpenCV ·
DeepFace · RetinaFace · Wav2Vec2

## About the Project

MHBAS (Multimodal Human Behaviour Analysis System) is a Windows desktop
application that performs continuous real-time behavioural analysis
using a standard webcam and microphone.

The system combines computer vision and speech processing to estimate: -
Stress Score (0--100) - Attention Score (0--100) - Distraction Heat

It was developed as a college mini-project exploring AI-based
behavioural monitoring.

## Features

### Real-time Multimodal Analysis

-   Face emotion recognition
-   Vocal emotion recognition using Wav2Vec2
-   Eye gaze direction detection
-   Head pose estimation
-   Blink and eye-closure monitoring

### Stress & Attention Scoring

-   Multimodal fusion of visual and audio signals
-   Smooth stress tracking using exponential moving average
-   Distraction detection
-   High-stress alert system

### Calibration

Two-phase personalised calibration: 1. Silence phase --- captures
environment and neutral pose 2. Speech phase --- captures vocal baseline

## Technologies Used

### Computer Vision

-   OpenCV
-   RetinaFace
-   DeepFace
-   TensorFlow
-   NumPy

### Audio Processing

-   Wav2Vec2
-   Transformers
-   PyTorch
-   SoundDevice
-   Librosa

### Interface

-   PyQt6
-   Matplotlib

## Project Structure

    mhbas/
    ├── appmain.py
    ├── app.py
    ├── video_worker.py
    ├── audio_worker.py
    ├── widgets.py
    ├── visuals.py
    ├── pages.py
    ├── installfonts.py
    └── requirements.txt

## Requirements

-   Windows 10/11
-   Python 3.10+
-   Webcam and microphone
-   NVIDIA GPU recommended (CUDA)

## Installation

``` bash
git clone https://github.com/Multimodal-Behaviour-Analysis-System/Multimodal-Human-Behaviour-Analysis-System.git

cd Multimodal-Human-Behaviour-Analysis-System

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

python installfonts.py

python appmain.py
```

## Usage

1.  Launch the application
2.  Start calibration
3.  Record a session
4.  View stress and attention metrics
5.  Export reports

## Limitations

-   Windows-only application
-   Requires proper lighting for accurate detection
-   Blink detection is an approximation
-   Session data is temporary unless exported

## License

This project is for educational and research purposes.
