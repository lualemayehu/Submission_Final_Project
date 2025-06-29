import pyaudio
import numpy as np
import threading
from collections import deque
import whisper

import cv2
import mediapipe as mp
from datetime import datetime

import torch
from facenet_pytorch import MTCNN
from ultralytics import YOLO


class ObjectDetector:
    def __init__(self, config):
        self.config = config['detection']['objects']
        self.class_map = {
            73: 'book',
            67: 'cell phone'
        }

        self.detection_interval = self.config['detection_interval']
        self.min_confidence = self.config['min_confidence']
        self.max_fps = self.config['max_fps']

        self.alert_logger = None
        self.frame_count = 0
        self.last_detection_time = datetime.now()

        self._initialize_model()

    def _initialize_model(self):
        try:
            self.model = YOLO('models/yolov8n.pt')
            self.model.overrides['conf'] = self.min_confidence
            self.model.overrides['device'] = 'cuda' if torch.cuda.is_available() else 'cpu'
            self.model.overrides['imgsz'] = 320
            self.model.overrides['iou'] = 0.45

            # Warm-up with a dummy image (as tensor might not suffice)
            dummy_img = np.zeros((320, 320, 3), dtype=np.uint8)
            self.model(dummy_img)

        except Exception as e:
            raise RuntimeError(f"Failed to initialize object detector: {str(e)}")

    def set_alert_logger(self, alert_logger):
        self.alert_logger = alert_logger

    def detect_objects(self, frame, visualize=False):
        current_time = datetime.now()
        if (current_time - self.last_detection_time).total_seconds() < (1.0 / self.max_fps):
            return False

        try:
            orig_h, orig_w = frame.shape[:2]
            target_w = 320
            target_h = int(orig_h * (target_w / orig_w))
            resized_frame = cv2.resize(frame, (target_w, target_h))

            scale_x = orig_w / target_w
            scale_y = orig_h / target_h

            results = self.model(resized_frame, verbose=False)
            detected = False

            for result in results:
                for box in result.boxes:
                    cls_id = int(box.cls)
                    conf = float(box.conf)

                    if cls_id in self.class_map and conf >= self.min_confidence:
                        label = self.class_map[cls_id]
                        detected = True

                        if self.alert_logger:
                            self.alert_logger.log_alert(
                                "FORBIDDEN_OBJECT",
                                f"Detected {label} with confidence {conf:.2f}"
                            )

                        if visualize:
                            x1, y1, x2, y2 = box.xyxy[0]
                            x1 = int(x1 * scale_x)
                            y1 = int(y1 * scale_y)
                            x2 = int(x2 * scale_x)
                            y2 = int(y2 * scale_y)

                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            cv2.putText(
                                frame, f"{label} {conf:.2f}",
                                (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                (0, 0, 255), 1
                            )

            self.last_detection_time = current_time
            return detected

        except Exception as e:
            if self.alert_logger:
                self.alert_logger.log_alert(
                    "OBJECT_DETECTION_ERROR",
                    f"Object detection failed: {str(e)}"
                )
            return False



class MultiFaceDetector:
    def __init__(self, config):
        multi_face_cfg = config['detection']['multi_face']
        self.alert_threshold = multi_face_cfg['alert_threshold']
        self.consecutive_frames = 0
        self.alert_logger = None

        self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        self.detector = MTCNN(
            keep_all=True,
            post_process=False,
            min_face_size=40,
            thresholds=[0.6, 0.7, 0.7],
            device=self.device
        )

    def set_alert_logger(self, logger):
        self.alert_logger = logger

    def detect_multiple_faces(self, frame):
        """Detects if multiple faces are present over consecutive frames."""
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        boxes, probs = self.detector.detect(rgb_frame)

        if boxes is not None and probs is not None:
            high_conf_faces = sum(p > 0.9 for p in probs if p is not None)

            if high_conf_faces >= 2:
                self.consecutive_frames += 1

                if self.consecutive_frames >= self.alert_threshold:
                    if self.alert_logger:
                        self.alert_logger.log_alert(
                            "MULTIPLE_FACES",
                            f"Detected {high_conf_faces} faces for {self.consecutive_frames} frames"
                        )
                    return True
            else:
                self.consecutive_frames = 0
        else:
            self.consecutive_frames = 0

        return False



class MouthMonitor:
    MOUTH_OPEN_THRESHOLD = 0.03
    MOUTH_WIDTH_THRESHOLD = 0.2

    def __init__(self, config):
        mouth_cfg = config['detection']['mouth']
        self.mouth_threshold = mouth_cfg['movement_threshold']
        self.mouth_movement_count = 0

        self.alert_logger = None

        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        # Landmark indices for mouth detection
        self.MOUTH_POINTS = {
            "upper_inner": 13,
            "lower_inner": 14,
            "right_corner": 78,
            "left_corner": 306
        }

    def set_alert_logger(self, logger):
        self.alert_logger = logger

    def monitor_mouth(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return False

        landmarks = results.multi_face_landmarks[0].landmark
        mouth_open = self.mouth_openness(landmarks)
        mouth_width = self.mouth_width(landmarks)

        if mouth_open > self.MOUTH_OPEN_THRESHOLD or mouth_width > self.MOUTH_WIDTH_THRESHOLD:
            self.mouth_movement_count += 1

            if self.mouth_movement_count > self.mouth_threshold and self.alert_logger:
                self.alert_logger.log_alert(
                    "MOUTH_MOVEMENT",
                    "Excessive mouth movement detected (possible talking)"
                )
                self.mouth_movement_count = 0
            return True

        self.mouth_movement_count = max(0, self.mouth_movement_count - 1)
        return False

    def mouth_openness(self, landmarks):
        upper = landmarks[self.MOUTH_POINTS["upper_inner"]].y
        lower = landmarks[self.MOUTH_POINTS["lower_inner"]].y
        return lower - upper

    def mouth_width(self, landmarks):
        left = landmarks[self.MOUTH_POINTS["left_corner"]].x
        right = landmarks[self.MOUTH_POINTS["right_corner"]].x
        return abs(left - right)


import cv2
import torch
from datetime import datetime
from facenet_pytorch import MTCNN


class FaceDetector:
    def __init__(self, config):
        face_cfg = config['detection']['face']
        self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        self.detector = MTCNN(
            keep_all=True,
            post_process=False,
            min_face_size=40,
            thresholds=[0.6, 0.7, 0.7],
            device=self.device
        )
        self.detection_interval = face_cfg['detection_interval']
        self.min_confidence = face_cfg['min_confidence']

        self.frame_count = 0
        self.face_present = False
        self.last_face_time = None
        self.face_disappeared_start = None
        self.alert_logger = None

    def set_alert_logger(self, logger):
        self.alert_logger = logger

    def detect_face(self, frame):
        self.frame_count += 1
        if self.frame_count % self.detection_interval != 0:
            return self.face_present

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        boxes, probs = self.detector.detect(rgb)

        current_time = datetime.now()

        if self.face_detected(boxes, probs):
            self.handle_face_present(current_time)
            return True
        else:
            self.handle_face_absent(current_time)
            return False

    def face_detected(self, boxes, probs):
        return boxes is not None and len(boxes) > 0 and probs[0] > self.min_confidence

    def handle_face_present(self, now):
        if not self.face_present and self.face_disappeared_start:
            disappeared_duration = (now - self.face_disappeared_start).total_seconds()
            if disappeared_duration > 5 and self.alert_logger:
                self.alert_logger.log_alert(
                    "FACE_REAPPEARED",
                    f"Face reappeared after {disappeared_duration:.1f} seconds"
                )

        self.face_present = True
        self.last_face_time = now
        self.face_disappeared_start = None

    def handle_face_absent(self, now):
        if self.face_present:
            self.face_disappeared_start = now

        self.face_present = False

        if self.last_face_time:
            disappeared_duration = (now - self.last_face_time).total_seconds()
            if disappeared_duration > 5 and self.alert_logger:
                self.alert_logger.log_alert(
                    "FACE_DISAPPEARED",
                    "Face disappeared for more than 5 seconds"
                )


class EyeTracker:
    LEFT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
    RIGHT_EYE_INDICES = [362, 385, 387, 263, 373, 380]
    NOSE_TIP_INDEX = 4

    def __init__(self, config):
        self.config = config['detection']['eyes']
        self.eye_threshold = self.config['gaze_threshold']

        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        self.gaze_direction = "center"
        self.eye_ratio = 0.3  # Default open eye ratio
        self.last_gaze_change = datetime.now()
        self.gaze_changes = 0
        self.alert_logger = None

    def set_alert_logger(self, logger):
        self.alert_logger = logger

    def calculate_ear(self, eye):
        A = np.linalg.norm(eye[1] - eye[5])
        B = np.linalg.norm(eye[2] - eye[4])
        C = np.linalg.norm(eye[0] - eye[3])
        return (A + B) / (2.0 * C)

    def get_eye_coords(self, landmarks, indices, frame_w, frame_h):
        return np.array([
            (landmarks[i].x * frame_w, landmarks[i].y * frame_h)
            for i in indices
        ])

    def get_gaze_direction(self, left_eye, right_eye, nose_tip):
        left_center = np.mean(left_eye, axis=0)
        right_center = np.mean(right_eye, axis=0)
        horiz_diff = ((left_center[0] + right_center[0]) / 2.0) - nose_tip[0]

        if horiz_diff < -15:
            return "left"
        elif horiz_diff > 15:
            return "right"
        return "center"

    def check_gaze_change(self, new_gaze):
        current_time = datetime.now()
        if new_gaze != self.gaze_direction:
            self.gaze_changes += 1
            self.gaze_direction = new_gaze
            self.last_gaze_change = current_time

        if self.gaze_changes > 3 and (current_time - self.last_gaze_change).total_seconds() < 2:
            if self.alert_logger:
                self.alert_logger.log_alert("EYE_MOVEMENT", "Excessive eye movement detected")
            self.gaze_changes = 0

    def track_eyes(self, frame):
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb)

            if not results.multi_face_landmarks:
                return self.gaze_direction, self.eye_ratio

            face = results.multi_face_landmarks[0]
            frame_h, frame_w = frame.shape[:2]

            left_eye = self.get_eye_coords(face.landmark, self.LEFT_EYE_INDICES, frame_w, frame_h)
            right_eye = self.get_eye_coords(face.landmark, self.RIGHT_EYE_INDICES, frame_w, frame_h)
            nose_tip = np.array([
                face.landmark[self.NOSE_TIP_INDEX].x * frame_w,
                face.landmark[self.NOSE_TIP_INDEX].y * frame_h
            ])

            # Eye aspect ratio
            left_ear = self.calculate_ear(left_eye)
            right_ear = self.calculate_ear(right_eye)
            self.eye_ratio = (left_ear + right_ear) / 2.0

            # Gaze direction and update check
            new_gaze = self.get_gaze_direction(left_eye, right_eye, nose_tip)
            self.check_gaze_change(new_gaze)

            return self.gaze_direction, self.eye_ratio

        except Exception as e:
            if self.alert_logger:
                self.alert_logger.log_alert("EYE_TRACKING_ERROR", f"Eye tracking error: {str(e)}")
            return self.gaze_direction, self.eye_ratio

class AudioMonitor:
    def __init__(self, config):
        self.load_config(config['detection']['audio_monitoring'])
        self.init_state()
        if self.whisper_enabled:
            self.load_whisper_model()

    def load_config(self, cfg):
        """Initialize config values."""
        self.sample_rate = cfg['sample_rate']
        self.chunk_size = 512  # 32ms for low-latency
        self.energy_threshold = cfg['energy_threshold']
        self.zcr_threshold = cfg['zcr_threshold']
        self.whisper_enabled = cfg['whisper_enabled']
        self.whisper_model_name = cfg['whisper_model']

    def init_state(self):
        """Initialize runtime state."""
        self.running = False
        self.audio_buffer = deque(maxlen=15)  # ~480ms
        self.thread = None
        self.alert_system = None
        self.alert_logger = None

    def load_whisper_model(self):
        """Load Whisper model if enabled."""
        self.whisper_model = whisper.load_model(self.whisper_model_name)

    def start(self):
        """Start audio monitoring in a background thread."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        """Stop audio monitoring thread safely."""
        self.running = False
        if self.thread and self.thread.isalive():
            self.thread.join(timeout=1)

    def run(self):
        """Continuously monitor audio input and process when voice is detected."""
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size
        )

        try:
            while self.running:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.int16)
                self.audio_buffer.append(audio)
                if self.is_voice(audio):
                    self.handle_voice_detection()
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

    def is_voice(self, audio):
        """Fast voice detection based on energy and zero-crossing rate."""
        audio_norm = audio / 32768.0
        energy = np.mean(audio_norm**2)
        if energy < self.energy_threshold:
            return False
        zcr = np.mean(np.abs(np.diff(np.sign(audio_norm))))
        return zcr <= self.zcr_threshold

    def handle_voice_detection(self):
        """Trigger alerts and optional speech analysis when voice is detected."""
        if self.alert_system:
            self.alert_system.speak_alert("VOICE_DETECTED")
        if self.alert_logger:
            self.alert_logger.log_alert("VOICE_DETECTED", "Voice activity detected")

        if self.whisper_enabled:
            self.process_with_whisper()

    def process_with_whisper(self):
        """Use Whisper to transcribe and analyze recent audio."""
        try:
            audio = np.concatenate(self.audio_buffer).astype(np.float32) / 32768.0
            result = self.whisper_model.transcribe(audio, fp16=False, language='en')
            text = result.get('text', '').strip().lower()

            if any(word in text for word in ['help', 'answer', 'whisper']):
                if self.alert_system:
                    self.alert_system.speak_alert("SPEECH_VIOLATION")
        except Exception as e:
            if self.alert_logger:
                self.alert_logger.log_alert("WHISPER_ERROR", str(e))
