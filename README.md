# Online Exam Cheating Detection System

Introduction

With the rapid growth of online education and remote learning, ensuring academic integrity during online examinations has become a significant challenge. Traditional proctoring methods are often impractical or ineffective in virtual environments, making it easier for dishonest behaviors to go unnoticed. To address this, the Online Exam Cheating Detection System has been developed as an advanced solution to monitor, detect, and prevent cheating during online exams.

This system leverages state-of-the-art computer vision and audio analysis technologies to continuously observe exam candidates in real-time. It performs comprehensive monitoring by tracking facial presence, eye movements, mouth activity, and the presence of multiple faces or suspicious objects within the camera’s view. Additionally, it incorporates audio monitoring to detect unauthorized sounds or conversations. Whenever a suspicious activity or rule violation is detected, the system immediately triggers alerts, records video evidence, and logs detailed reports for further review.

The primary objective of this system is to uphold fairness and trust in online assessments by deterring cheating and ensuring that students adhere to exam regulations. By automating the proctoring process, it reduces the need for human invigilators, enhances exam security, and provides institutions with reliable documentation of any violations. Ultimately, the Online Exam Cheating Detection System fosters a credible and equitable examination environment that supports the integrity of remote learning.
## Features

- **Face Presence Detection**: Identifies when student's face is not visible
- **Eye Movement Tracking**: Detects excessive eye movements (left/right/up/down)
- **Gaze Analysis**: Monitors direction of eye gaze
- **Mouth Movement Detection**: Identifies potential talking or whispering
- **Multi-Face Detection**: Alerts when multiple faces appear in frame
- **Real-time Alerts**: Flags suspicious activities with timestamps
- **Object Delection**: Object Detection: Detects prohibited objects (cell phone, book, etc.).
- **Screen Recoding**: Continuously captures examinee's screen activity
- **Audio Detection**: Monitors for voice/whispering in student's environment
- **Alert Speaker**: Delivers real-time verbal warnings via text-to-speech
- **Report Generation**: Creates detailed visual PDF and HTML reports with violations summary, heatmaps, and activity timeline  


## Technologies Used

- Python 3.11+
- OpenCV (for computer vision)
- MediaPipe (for face mesh and landmark detection)
- FaceNet-PyTorch (for face detection)
- MTCNN (for face detection)


## Installation

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Download pre-trained models (if needed):
```bash
python -c "from facenet_pytorch import MTCNN; MTCNN(keep_all=True)"
```

## Usage

1. Configure the system by editing `config.yaml`:
```yaml
video:
  source: 0                   # 0 for default webcam
  resolution: [1280, 720]
  fps: 30
  recording_path: "./recordings"

screen:
  monitor_index: 0           # 0 for primary monitor
  fps: 15                    # Lower FPS for screen recording
  recording: true            # Enable/disable screen recording


detection:
  face:
    detection_interval: 5     # frames
    min_confidence: 0.8
  eyes:
    gaze_threshold: 2          # seconds
    blink_threshold: 0.3       # EAR threshold for blink detection
    gaze_sensitivity: 15       # pixels threshold for gaze detection
    consecutive_frames: 3      # frames for gaze change detection
  mouth:
    movement_threshold: 3     # consecutive frames
  multi_face:
    alert_threshold: 5        # frames
  objects:
    min_confidence: 0.65  # Detection confidence threshold
    detection_interval: 5 # frames between detections
    max_fps: 5            # Maximum detection frames per second
  audio_monitoring:
    enabled: true
    sample_rate: 16000
    energy_threshold: 0.001
    zcr_threshold: 0.35
    whisper_enabled: false  # Enable only when needed
    whisper_model: "tiny.en"
        
logging:
  log_path: "./logs"
  alert_cooldown: 10          # seconds
  alert_system:
    voice_alerts: true  # Enable/disable voice alerts
    alert_volume: 0.8   # Volume level (0.0 to 1.0)
    cooldown: 10        # Minimum seconds between same alert
```

2.Run the main detection system:
```bash
python app.py
```

## System Architecture


## Customization
You can adjust detection thresholds in `config.yaml`:
```yaml
eyes:
  gaze_threshold: 2      # seconds of gaze deviation to trigger alert
  blink_threshold: 0.3   # eye aspect ratio for blink detection

mouth:
  movement_threshold: 3  # consecutive frames of mouth movement
```

