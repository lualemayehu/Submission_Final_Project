import cv2
import yaml
from datetime import datetime


from detection_system import AudioMonitor, EyeTracker,FaceDetector,MouthMonitor, ObjectDetector, MultiFaceDetector
from report import AlertSystem,AlertLogger,VideoRecorder,ScreenRecorder,ViolationLogger,ViolationCapturer, ReportGenerator


def load_config():
    with open('config.yaml') as f:
        return yaml.safe_load(f)


def display_detection_results(frame, results):
    y_offset = 30
    line_height = 30

    status_items = [
        f"Face: {'Present' if results['face_present'] else 'Absent'}",
        f"Gaze: {results['gaze_direction']}",
        f"Eyes: {'Open' if results['eye_ratio'] > 0.25 else 'Closed'}",
        f"Mouth: {'Moving' if results['mouth_moving'] else 'Still'}"
    ]

    alert_items = []
    if results['multiple_faces']:
        alert_items.append("Multiple Faces Detected!")
    if results['objects_detected']:
        alert_items.append("Suspicious Object Detected!")

    for item in status_items + alert_items:
        color = (0, 255, 0) if item in status_items else (0, 0, 255)
        cv2.putText(frame, item, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        y_offset += line_height

    cv2.putText(frame, results['timestamp'], (frame.shape[1] - 250, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)


def handle_violation(violation_type, frame, results, alert_system, capturer, logger):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    alert_system.speak_alert(violation_type)
    image = capturer.capture_violation(frame, violation_type, timestamp)
    logger.log_violation(
        violation_type, timestamp,
        {'duration': '5+ seconds', 'frame': results}
    )


def initialize_detectors(config, alert_logger):
    detectors = [
        FaceDetector(config),
        EyeTracker(config),
        MouthMonitor(config),
        MultiFaceDetector(config),
        ObjectDetector(config)
    ]
    for detector in detectors:
        if hasattr(detector, 'set_alert_logger'):
            detector.set_alert_logger(alert_logger)
    return detectors


def main():
    config = load_config()
    alert_logger = AlertLogger(config)
    alert_system = AlertSystem(config)
    capturer = ViolationCapturer(config)
    logger = ViolationLogger(config)
    report_generator = ReportGenerator(config)

    student_info = {
        'id': 'STUDENT_001',
        'name': 'John Doe',
        'exam': 'Final Examination',
        'course': 'Computer Science 101'
    }

    video_recorder = VideoRecorder(config)
    screen_recorder = ScreenRecorder(config)
    audio_monitor = AudioMonitor(config)
    audio_monitor.alert_system = alert_system
    audio_monitor.alert_logger = alert_logger

    if config['detection'].get('audio_monitoring'):
        audio_monitor.start()

    try:
        if config['screen'].get('recording'):
            screen_recorder.start_recording()

        detectors = initialize_detectors(config, alert_logger)
        video_recorder.start_recording()

        cap = cv2.VideoCapture(config['video']['source'])
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config['video']['resolution'][0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config['video']['resolution'][1])

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            results = {
                'face_present': detectors[0].detect_face(frame),
                'gaze_direction': 'Center',
                'eye_ratio': 0.3,
                'mouth_moving': False,
                'multiple_faces': False,
                'objects_detected': False,
                'timestamp': now
            }

            # Update other results
            results['gaze_direction'], results['eye_ratio'] = detectors[1].track_eyes(frame)
            results['mouth_moving'] = detectors[2].monitor_mouth(frame)
            results['multiple_faces'] = detectors[3].detect_multiple_faces(frame)
            results['objects_detected'] = detectors[4].detect_objects(frame)

            # Handle violations
            if not results['face_present']:
                handle_violation("FACE_DISAPPEARED", frame, results, alert_system, capturer, logger)
            elif results['multiple_faces']:
                handle_violation("MULTIPLE_FACES", frame, results, alert_system, capturer, logger)
            elif results['objects_detected']:
                handle_violation("OBJECT_DETECTED", frame, results, alert_system, capturer, logger)
            elif results['mouth_moving']:
                handle_violation("MOUTH_MOVING", frame, results, alert_system, capturer, logger)

            # Display and record
            display_detection_results(frame, results)
            video_recorder.record_frame(frame)

            cv2.imshow('Exam Proctoring', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        violations = logger.get_violations()
        report_path = report_generator.generate_report(student_info, violations)
        print(f"Report generated: {report_path}")

        if config['screen'].get('recording'):
            screen_data = screen_recorder.stop_recording()
            print(f"Screen recording saved: {screen_data['filename']}")

        video_data = video_recorder.stop_recording()
        print(f"Webcam recording saved: {video_data['filename']}")

        if cap and cap.isOpened():
            cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
