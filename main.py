from flask import Flask, render_template, request, redirect, url_for, session,flash, Response, send_file
from flask_mysql_connector import MySQL
import MySQLdb.cursors
import re
import os
import sys
from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash
from functools import wraps
import cv2
import yaml
from datetime import datetime, timedelta


from detection_system import AudioMonitor, EyeTracker, FaceDetector, MouthMonitor, ObjectDetector, MultiFaceDetector
from report import AlertSystem, AlertLogger, VideoRecorder, ScreenRecorder, ViolationLogger, ViolationCapturer, ReportGenerator



app = Flask(__name__)
app.secret_key = os.urandom(24)

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Mysql@123' 
app.config['MYSQL_DATABASE'] = 'exam'


mysql = MySQL(app)

# Load config
with open('config.yaml') as f:
    config = yaml.safe_load(f)

# Initialize global resources
alert_logger = AlertLogger(config)
alert_system = AlertSystem(config)
capturer = ViolationCapturer(config)
logger = ViolationLogger(config)
report_generator = ReportGenerator(config)
video_recorder = VideoRecorder(config)
screen_recorder = ScreenRecorder(config)
audio_monitor = AudioMonitor(config)
audio_monitor.alert_system = alert_system
audio_monitor.alert_logger = alert_logger

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

cap = cv2.VideoCapture(config['video']['source'])
cap.set(cv2.CAP_PROP_FRAME_WIDTH, config['video']['resolution'][0])
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config['video']['resolution'][1])



def handle_violation(violation_type, frame, results):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    alert_system.speak_alert(violation_type)
    capturer.capture_violation(frame, violation_type, timestamp)
    logger.log_violation(
        violation_type, timestamp,
        {'duration': '5+ seconds', 'frame': results}
    )


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
    return frame


def generate_video_stream():
    video_recorder.start_recording()
    if config['screen'].get('recording'):
        screen_recorder.start_recording()

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

        results['gaze_direction'], results['eye_ratio'] = detectors[1].track_eyes(frame)
        results['mouth_moving'] = detectors[2].monitor_mouth(frame)
        results['multiple_faces'] = detectors[3].detect_multiple_faces(frame)
        results['objects_detected'] = detectors[4].detect_objects(frame)

        # Handle violations
        if not results['face_present']:
            handle_violation("FACE_DISAPPEARED", frame, results)
        elif results['multiple_faces']:
            handle_violation("MULTIPLE_FACES", frame, results)
        elif results['objects_detected']:
            handle_violation("OBJECT_DETECTED", frame, results)
        elif results['mouth_moving']:
            handle_violation("MOUTH_MOVING", frame, results)

        frame = display_detection_results(frame, results)
        video_recorder.record_frame(frame)

        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'loggedin' not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def role_required(*roles):
    """Allow access only to the given role names (“admin”, “student”, …)."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get('loggedin'):
                flash("Please log in first", "warning")
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash("You’re not authorised to view this page", "danger")
                return redirect(url_for('home'))
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash("Please enter both username and password.", "warning")
            return render_template('auth/login.html', title="Login")

        cursor = mysql.connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()

        if user and check_password_hash(user['password_hash'], password):
            session['loggedin'] = True
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash("Login successful!", "success")
            return redirect(url_for('home'))  # or redirect to admin/student page
        else:
            flash("Invalid username or password.", "danger")
            return render_template('auth/login.html', title="Login")

    return render_template('auth/login.html', title="Login")



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', 'student').strip()  # Default to 'student'

        # Basic validation
        if not username or not password or not email:
            flash("All fields are required.", "danger")
            return render_template('auth/register.html', title="Register")

        if not re.match(r'^[A-Za-z0-9]+$', username):
            flash("Username must contain only letters and numbers.", "danger")
            return render_template('auth/register.html', title="Register")

        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            flash("Invalid email address.", "danger")
            return render_template('auth/register.html', title="Register")

        if role not in ['student', 'admin']:
            flash("Invalid role selected.", "danger")
            return render_template('auth/register.html', title="Register")

        # Check for existing user
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s OR email = %s", (username, email))
        account = cursor.fetchone()
        

        if account:
            flash("An account with that username or email already exists.", "danger")
            return render_template('auth/register.html', title="Register")

        # Hash the password
        password_hash = generate_password_hash(password)

        # Insert new user
        cursor.execute("""
            INSERT INTO Users (username, password_hash, email, role)
            VALUES (%s, %s, %s, %s)
        """, (username, password_hash, email, role))
        mysql.connection.commit()

        flash("You have successfully registered! Please log in.", "success")
        return redirect(url_for('login'))

    # GET method
    return render_template('auth/register.html', title="Register")


@app.route('/')
@login_required               
def home():
    return redirect(url_for('admin_dashboard' if session['role'] == 'admin' else 'student_dashboard'))

@app.route('/home')
@role_required('admin')
def admin_dashboard():
    # put whatever admin sees here; e.g. recent exams, metrics, etc.
    return render_template('home/home.html',username=session['username'],title="Admin Dashboard")

@app.route('/student')
@role_required('student')
def student_dashboard():

    notifications = ["Exam starts at 10:00 AM", "No electronic devices allowed"]
    exam_questions = [
                    {"question": "Which of the following is the correct way to assign the string 'Hello World' to a variable named `var` in Python?", "id": 1},
                    {"question": "What data type does the number `5` represent in Python?", "id": 2},
                    {"question": "Which of the following Python code snippets will print numbers from 0 to 4?", "id": 3},
                    {"question": "How do you define a function named `my_function` in Python?", "id": 4},
                    {"question": "Which Python function is used to get the number of items in a list called `my_list`?", "id": 5},
                    {"question": "How do you write a single-line comment in Python?", "id": 6},
                    {"question": "Which of the following is the correct way to create a dictionary in Python?", "id": 7},
                    {"question": "What is the output of `str(25)` in Python?", "id": 8},
                    {"question": "Which of the following is the correct syntax for an `if-else` statement in Python?", "id": 9},
                    {"question": "How do you create a tuple in Python?", "id": 10}
                ]

    exam_start = datetime.now()
    exam_duration = timedelta(minutes=90)  

    return render_template(
                'home/student.html',
                username       = session['username'],
                notifications  = notifications,
                exam_questions = exam_questions,
                exam_start     = exam_start.isoformat(),
                exam_end       = (exam_start + exam_duration).isoformat(),
                title          = "Student Dashboard"
            )   

@app.route('/video_feed')
def video_feed():
    return Response(generate_video_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/download_report')
@login_required
def download_report():
    student_info = {
        'id': 'STUDENT_001',
        'name': session.get('username', 'John David'),
        'exam': 'Final Examination',
        'course': 'Computer Science 101'
    }

    violations = logger.get_violations()

    report_path = report_generator.generate_report_fpdf(student_info, violations)
    
    if report_path:
        return send_file(report_path, as_attachment=True)
    else:
        flash("Failed to generate report.", "danger")
        return redirect(url_for('home'))
    
@app.route('/base_report/<student_id>')
@login_required
def preview_report(student_id):
    # Example: fetch student info and violations from DB or logger
    # For demo, let's hardcode or fetch from wherever you store them

    # Sample student info (replace with DB fetch)
    student_info = {
        'id': student_id,
        'name': 'John David',
        'exam': 'Final Examination',
        'course': 'Computer Science 101'
    }

    # Sample violations list (replace with real data)
    violations = logger.get_violations()  # or your source of violation dicts

    # Create report data like in ReportGenerator but render HTML directly
    report_generator = ReportGenerator(config)
    report_data = {
        'student': student_info,
        'violations': violations,
        'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'stats': report_generator.calculate_stats(violations),
        'timeline_image': report_generator.generate_timeline(violations, student_id),
        'heatmap_image': report_generator.generate_heatmap(violations, student_id),
        'severity_map': report_generator.severity_map,
        'has_images': True  # or check if images exist
    }

    return render_template('home/base_report.html', **report_data)
    


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    response = render_template('auth/login.html')
    return response


if __name__ =='__main__':
	app.run(debug=True)
