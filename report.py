import os
import tempfile
import time
import threading
from gtts import gTTS
import pygame
import json
from datetime import datetime

from fpdf import FPDF

import cv2
import numpy as np
from mss import mss


import pdfkit
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
from jinja2 import Environment, FileSystemLoader
import matplotlib.pyplot as plt
import logging

class ReportGenerator:
    def __init__(self, config):
        self.config = config.get('reporting', {})
        self.output_dir = self.config.get('output_dir', './reports/generated')
        self.image_dir = os.path.join(self.output_dir, 'images')
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.image_dir, exist_ok=True)
        
        template_path = os.path.join(os.path.dirname(__file__), 'templates')
        self.template_env = Environment(loader=FileSystemLoader(template_path))
        
        self.logger = logging.getLogger('ReportGenerator')
        self.logger.setLevel(logging.INFO)
        
        # Map violation types to severity (default 1)
        self.severity_map = {
            'FACE_DISAPPEARED': 1,
            'GAZE_AWAY': 2,
            'MOUTH_MOVING': 3,
            'MULTIPLE_FACES': 4,
            'OBJECT_DETECTED': 5,
            'AUDIO_DETECTED': 3
        }
        
    def generate_report(self, student_info, violations, output_format='pdf'):
        try:
            report_data = {
                'student': student_info,
                'violations': violations,
                'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'stats': self.calculate_stats(violations),
                'timeline_image': self.generate_timeline(violations, student_info['id']),
                'heatmap_image': self.generate_heatmap(violations, student_info['id']),
            }
            report_data['has_images'] = bool(report_data['timeline_image'] or report_data['heatmap_image'])

            template = self.template_env.get_template('base_report.html')
            html_content = template.render(report_data)

            filename = f"report_{student_info['id']}_{datetime.now():%Y%m%d_%H%M%S}.{output_format.lower()}"
            output_path = os.path.join(self.output_dir, filename)

            if output_format.lower() == 'pdf':
                options = {
                    'enable-local-file-access': None,
                    'quiet': '',
                    'margin-top': '10mm',
                    'margin-right': '10mm',
                    'margin-bottom': '10mm',
                    'margin-left': '10mm'
                }
                wkhtmltopdf_path = self.config.get('wkhtmltopdf_path')
                config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path) if wkhtmltopdf_path else None
                pdfkit.from_string(html_content, output_path, options=options, configuration=config)
            else:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)

            self.logger.info(f"Report generated at: {output_path}")
            return output_path

        except Exception as e:
            self.logger.error(f"Failed to generate report: {e}")
            return None

    def generate_report_fpdf(self, student_info, violations):
        try:
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()

            # Fonts
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(0, 10, "Student Exam Monitoring Report", ln=True, align='C')

            pdf.set_font("Arial", '', 12)
            pdf.cell(0, 10, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
            pdf.ln(10)

            # Student Info
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, "Student Information", ln=True)
            pdf.set_font("Arial", '', 12)
            for key, value in student_info.items():
                pdf.cell(0, 8, f"{key.capitalize()}: {value}", ln=True)
            pdf.ln(5)

            # Summary Stats
            stats = self.calculate_stats(violations)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, "Summary Statistics", ln=True)
            pdf.set_font("Arial", '', 12)
            pdf.cell(0, 8, f"Total Violations: {stats['total']}", ln=True)
            pdf.cell(0, 8, f"Average Severity: {stats['average_severity']:.2f}", ln=True)
            pdf.cell(0, 8, f"Duration: {stats['timeline'][-1]['time'] if stats['timeline'] else 'N/A'}", ln=True)
            pdf.ln(5)

            # Insert Heatmap
            heatmap_path = self.generate_heatmap(violations, student_info['id'])
            if heatmap_path and os.path.exists(heatmap_path):
                pdf.set_font("Arial", 'B', 14)
                pdf.cell(0, 10, "Violation Heatmap", ln=True)
                pdf.image(heatmap_path, w=180)
                pdf.ln(10)

            # Insert Timeline
            timeline_path = self.generate_timeline(violations, student_info['id'])
            if timeline_path and os.path.exists(timeline_path):
                pdf.set_font("Arial", 'B', 14)
                pdf.cell(0, 10, "Violation Timeline", ln=True)
                pdf.image(timeline_path, w=180)
                pdf.ln(10)

            # Violation List
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, "Violation Details", ln=True)
            pdf.set_font("Arial", '', 12)
            for v in violations:
                pdf.cell(0, 8, f"{v['timestamp']} - {v['type']}", ln=True)

            # Optional: Screenshots (if available)
            image_files = [f for f in os.listdir(self.image_dir) if f.startswith(student_info['id']) and f.endswith('.jpg')]
            if image_files:
                pdf.add_page()
                pdf.set_font("Arial", 'B', 14)
                pdf.cell(0, 10, "Snapshots", ln=True)
                pdf.ln(5)
                for img in image_files:
                    img_path = os.path.join(self.image_dir, img)
                    if os.path.exists(img_path):
                        pdf.image(img_path, w=180)
                        pdf.ln(5)

            # Save PDF
            filename = f"report_{student_info['id']}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
            output_path = os.path.join(self.output_dir, filename)
            pdf.output(output_path)

            self.logger.info(f"PDF report generated at: {output_path}")
            return output_path

        except Exception as e:
            self.logger.error(f"Failed to generate fpdf2 report: {e}")
            return None

    def calculate_stats(self, violations):
        stats = {'total': len(violations), 'by_type': {}, 'timeline': [], 'severity_score': 0}

        for violation in violations:
            vtype = violation['type']
            severity = self.severity_map.get(vtype, 1)
            stats['by_type'][vtype] = stats['by_type'].get(vtype, 0) + 1
            stats['timeline'].append({'time': violation['timestamp'], 'type': vtype, 'severity': severity})
            stats['severity_score'] += severity

        stats['average_severity'] = (stats['severity_score'] / stats['total']) if stats['total'] else 0
        return stats

    def generate_timeline(self, violations, student_id):
        if not violations:
            return None
        try:
            times, severities, labels = [], [], []
            for v in violations:
                times.append(datetime.strptime(v['timestamp'], "%Y%m%d_%H%M%S_%f"))
                labels.append(v['type'])
                severities.append(self.severity_map.get(v['type'], 1))

            plt.figure(figsize=(12, 5))
            plt.plot(times, severities, 'o-', markersize=8)

            for t, s, l in zip(times, severities, labels):
                plt.annotate(l, (t, s), textcoords="offset points", xytext=(0, 10), ha='center', fontsize=8)

            plt.title(f"Violation Timeline - {student_id}")
            plt.xlabel("Time")
            plt.ylabel("Severity Level")
            plt.grid(True, linestyle='--', alpha=0.7)
            plt.xticks(rotation=45)
            plt.tight_layout()

            path = os.path.join(self.image_dir, f'timeline_{student_id}.png')
            plt.savefig(path, dpi=150, bbox_inches='tight')
            plt.close()
            return path

        except Exception as e:
            self.logger.error(f"Failed to generate timeline: {e}")
            return None

    def generate_heatmap(self, violations, student_id):
        if not violations:
            return None
        try:
            counts = {}
            for v in violations:
                counts[v['type']] = counts.get(v['type'], 0) + 1

            if not counts:
                return None

            types, values = zip(*sorted(counts.items(), key=lambda x: x[1], reverse=True))
            colors = [plt.cm.Reds(self.severity_map.get(t, 1) / 5) for t in types]

            plt.figure(figsize=(10, 5))
            bars = plt.barh(types, values, color=colors, edgecolor='black', linewidth=0.7)

            for bar in bars:
                width = bar.get_width()
                plt.text(width + 0.3, bar.get_y() + bar.get_height() / 2, str(int(width)), va='center', ha='left', fontsize=10)

            plt.title(f"Violation Frequency - {student_id}")
            plt.xlabel("Count")
            plt.ylabel("Violation Type")
            plt.grid(True, linestyle='--', alpha=0.3, axis='x')
            plt.tight_layout()

            path = os.path.join(self.image_dir, f'heatmap_{student_id}.png')
            plt.savefig(path, dpi=150, bbox_inches='tight')
            plt.close()
            return path

        except Exception as e:
            self.logger.error(f"Failed to generate heatmap: {e}")
            return None



class ViolationLogger:
    def __init__(self, config):
        self.log_file = os.path.join(config['global']['output_path'], "violations.json")
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        self.violations = []
        self.load_from_file()
        
    def log_violation(self, violation_type, timestamp=None, metadata=None):
        """Log a violation with optional timestamp and metadata."""
        entry = {
            'type': violation_type,
            'timestamp': timestamp or datetime.now().isoformat(),
            'metadata': metadata or {}
        }
        self.violations.append(entry)
        self.save_to_file()
        
    def save_to_file(self):
        """Persist violations to JSON file."""
        with open(self.log_file, 'w') as f:
            json.dump(self.violations, f, indent=2)
            
    def load_from_file(self):
        """Load existing violations from JSON file if available."""
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'r') as f:
                    self.violations = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.violations = []
                
    def get_violations(self):
        """Return the list of all logged violations."""
        return self.violations


class VideoRecorder:
    def __init__(self, config):
        video_cfg = config['video']
        self.recording_path = video_cfg['recording_path']
        self.resolution = tuple(video_cfg['resolution'])
        self.fps = video_cfg['fps']
        self.writer = None
        self.filename = None
        self.frame_count = 0
        self.start_time = None
        
    def start_recording(self):
        os.makedirs(self.recording_path, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = os.path.join(self.recording_path, f"webcam_{timestamp}.mp4")
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.writer = cv2.VideoWriter(self.filename, fourcc, self.fps, self.resolution)
        
        self.frame_count = 0
        self.start_time = datetime.now()
        
    def record_frame(self, frame):
        if self.writer is not None:
            self.writer.write(frame)
            self.frame_count += 1
            
    def stop_recording(self):
        if self.writer is None:
            return None
        
        self.writer.release()
        self.writer = None
        
        duration = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        actual_fps = self.frame_count / duration if duration > 0 else 0
        
        return {
            'filename': self.filename,
            'frame_count': self.frame_count,
            'duration': duration,
            'fps': actual_fps
        }



class ViolationCapturer:
    def __init__(self, config):
        self.output_dir = os.path.join(config['global']['output_path'], "violation_captures")
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_filename(self, violation_type, timestamp):
        """Generates a descriptive filename for the captured image."""
        return f"{violation_type}_{timestamp}.jpg"

    def draw_label(self, frame, text):
        """Overlay violation label text on frame."""
        labeled_frame = frame.copy()
        cv2.putText(
            labeled_frame,
            text,
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2
        )
        return labeled_frame

    def capture_violation(self, frame, violation_type, timestamp=None):
        """
        Saves an annotated image of the current frame upon violation.
        Returns metadata including the saved path.
        """
        timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        label_text = f"{violation_type} - {timestamp}"
        filename = self.generate_filename(violation_type, timestamp)
        save_path = os.path.join(self.output_dir, filename)

        labeled_frame = self.draw_label(frame, label_text)
        cv2.imwrite(save_path, labeled_frame)

        return {
            'type': violation_type,
            'timestamp': timestamp,
            'image_path': os.path.abspath(save_path)
        }


class ScreenRecorder:
    def __init__(self, config):
        self.config = config['screen']
        self.fps = self.config['fps']
        self.monitor_index = self.config['monitor_index']
        self.recording_path = config['video']['recording_path']

        self.writer = None
        self.sct = None
        self.monitor = None
        self.filename = None
        self.frame_count = 0

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None

    def get_monitor_config(self):
        """Determine which monitor to capture."""
        self.sct = mss()
        monitors = self.sct.monitors
        index = self.monitor_index + 1  # mss.monitor[0] is a virtual monitor (all screens)

        if len(monitors) > index:
            return monitors[index]
        return monitors[1]  # Default to primary monitor

    def initialize_writer(self):
        """Prepare the video writer."""
        if not os.path.exists(self.recording_path):
            os.makedirs(self.recording_path)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = os.path.join(self.recording_path, f"screen_{timestamp}.mp4")

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.writer = cv2.VideoWriter(
            self.filename, fourcc, self.fps,
            (self.monitor['width'], self.monitor['height'])
        )

    def start_recording(self):
        """Start the screen recording process."""
        self.monitor = self.get_monitor_config()
        self.initialize_writer()

        self.frame_count = 0
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.thread.start()

    def capture_loop(self):
        """Continuously capture and write frames in a background thread."""
        self.sct = mss()  # Must be initialized in the thread

        while not self.stop_event.is_set():
            with self.lock:
                screenshot = self.sct.grab(self.monitor)
                frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_BGRA2BGR)

                if self.writer:
                    self.writer.write(frame)
                    self.frame_count += 1

            time.sleep(1.0 / self.fps)

    def stop_recording(self):
        """Safely stop recording and release resources."""
        self.stop_event.set()
        if self.thread:
            self.thread.join()
            self.thread = None

        with self.lock:
            if self.writer:
                self.writer.release()
                self.writer = None

        return {
            'filename': self.filename,
            'frame_count': self.frame_count,
            'duration': self.frame_count / self.fps if self.fps else 0
        }


class AlertLogger:
    def __init__(self, config):
        self.log_path = config['logging']['log_path']
        self.cooldown = config['logging']['alert_cooldown']
        self.last_alert_time = {}
        self.alerts = []

        os.makedirs(self.log_path, exist_ok=True)
        self.log_file = os.path.join(self.log_path, "alerts.log")

    def within_cooldown(self, alert_type, now_ts):
        """Check if alert type is still in cooldown period."""
        last_ts = self.last_alert_time.get(alert_type)
        return last_ts is not None and (now_ts - last_ts) < self.cooldown

    def write_to_file(self, entry):
        """Safely append a log entry to file."""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception as e:
            print(f"[AlertLogger] Failed to write to log file: {e}")

    def log_alert(self, alert_type, message):
        """Log an alert if it's outside its cooldown window."""
        now = datetime.now()
        now_ts = now.timestamp()

        if self.within_cooldown(alert_type, now_ts):
            return None

        self.last_alert_time[alert_type] = now_ts
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{timestamp} - {alert_type.upper()}: {message}"
        self.alerts.append(entry)
        self.write_to_file(entry)

        return entry


class AlertSystem:
    def __init__(self, config):
        pygame.mixer.init()
        self.config = config
        self.alert_cooldown = config['logging']['alert_cooldown']
        self.last_alert_time = {}

        self.alerts = {
            "FACE_DISAPPEARED": "Please look at the screen",
            "FACE_REAPPEARED": "Thank you for looking at the screen",
            "MULTIPLE_FACES": "We detected multiple people",
            "OBJECT_DETECTED": "Unauthorized object detected",
            "GAZE_AWAY": "Please focus on your screen",
            "MOUTH_MOVING": "Please maintain silence during exam",
            "SPEECH_VIOLATION": "Speaking during exam is not allowed",
            "VOICE_DETECTED": "We detected voice, please maintain silence during the exam",
        }

    def can_trigger(self, alert_type):
        """Returns True if the cooldown period has passed."""
        now = time.time()
        last = self.last_alert_time.get(alert_type, 0)
        return (now - last) >= self.alert_cooldown

    def log_alert_time(self, alert_type):
        """Update last alert timestamp."""
        self.last_alert_time[alert_type] = time.time()

    def speak_alert(self, alert_type):
        """Convert alert message to speech and play it (non-blocking)."""
        if alert_type not in self.alerts or not self.can_trigger(alert_type):
            return

        self.log_alert_time(alert_type)
        message = self.alerts[alert_type]

        def _play():
            try:
                tts = gTTS(text=message, lang='en')
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                    temp_path = tmp_file.name
                    tts.save(temp_path)

                pygame.mixer.music.load(temp_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            except Exception as e:
                print(f"[AlertSystem] Audio playback failed: {e}")
            finally:
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    os.unlink(temp_path)

        threading.Thread(target=_play, daemon=True).start()
