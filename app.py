import os
import shutil
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, Response
from werkzeug.utils import secure_filename
import config
from core.attendance import (
    load_students, write_student_to_master, soft_delete_student,
    SessionManager, get_session_history, delete_session, generate_weekly_report_excel
)
from core.encoder import register_student_encodings, delete_student_encoding
from core.recognition import tracker_instance

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Ensure uploads folder is ready
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Start the camera tracker on app start
# Check WERKZEUG_RUN_MAIN environment variable to avoid starting double threads in Flask's debug reloader
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    tracker_instance.start()

@app.route('/')
def index():
    """Main dashboard showing live feed and attendance stats."""
    active_sess = SessionManager.get_active_session()
    return render_template('index.html', active_session=active_sess)

@app.route('/video_feed')
def video_feed():
    """MJPEG stream endpoint consumed by img tag."""
    def generate():
        while True:
            frame = tracker_instance.get_frame_jpeg()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            # 20 FPS stream
            import time
            time.sleep(0.05)
            
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/session/status')
def session_status():
    """Active session status JSON endpoint."""
    active_sess = SessionManager.get_active_session()
    if active_sess:
        return jsonify({
            "active": True,
            "subject": active_sess['subject'],
            "section": active_sess['section'],
            "start_time": active_sess['start_time'],
            "total_enrolled": active_sess['total_enrolled']
        })
    return jsonify({"active": False})

@app.route('/api/attendance')
def get_attendance():
    """Active session attendance records JSON endpoint."""
    active_sess = SessionManager.get_active_session()
    if not active_sess:
        return jsonify({"active": False, "records": []})
        
    # Get all students enrolled in this section to compute present/absent
    all_students = load_students()
    enrolled_students = [
        {"roll_number": s['roll_number'], "name": s['name']}
        for s in all_students if s['section'] == active_sess['section']
    ]
    
    records_list = list(active_sess['records'].values())
    
    return jsonify({
        "active": True,
        "session_id": active_sess['session_id'],
        "present_count": len(records_list),
        "total_enrolled": active_sess['total_enrolled'],
        "records": records_list,
        "enrolled_students": enrolled_students
    })

# Admin routes with password protection
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    """Admin dashboard login and control view."""
    if request.method == 'POST':
        # Handle Logout
        if request.form.get('logout'):
            session.pop('admin_logged_in', None)
            flash('Logged out successfully.', 'success')
            return redirect(url_for('admin'))
            
        # Handle Login
        password = request.form.get('password')
        if password == config.ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash('Access Authorized.', 'success')
        else:
            flash('Incorrect Admin Password.', 'error')
            
        return redirect(url_for('admin'))
        
    # GET Request
    active_sess = SessionManager.get_active_session()
    students_list = load_students(active_only=True)
    sessions_history = get_session_history()
    
    current_config = {
        "threshold": config.RECOGNITION_THRESHOLD,
        "interval": config.RECOGNITION_INTERVAL,
        "model": config.FACE_DETECTION_MODEL,
        "camera": config.CAMERA_INDEX
    }
    
    return render_template(
        'admin.html',
        active_session=active_sess,
        students_list=students_list,
        sessions_history=sessions_history,
        current_config=current_config
    )

@app.route('/admin/config', methods=['POST'])
def save_config():
    """Modify core face recognition configuration parameters."""
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "Unauthorized"}), 403
        
    try:
        config.RECOGNITION_THRESHOLD = float(request.form.get('threshold', 0.60))
        config.RECOGNITION_INTERVAL = int(request.form.get('interval', 3))
        config.FACE_DETECTION_MODEL = request.form.get('model', 'hog')
        
        # Parse Camera Index (int) or Camera URL (str)
        camera_input = request.form.get('camera', '0')
        try:
            config.CAMERA_INDEX = int(camera_input)
        except ValueError:
            config.CAMERA_INDEX = camera_input
        
        # Tell tracker to reload settings & release current camera
        tracker_instance.reload_db()
        flash('System configuration updated successfully.', 'success')
    except Exception as e:
        flash(f'Error updating configuration: {e}', 'error')
        
    return redirect(url_for('admin'))

@app.route('/admin/session/start', methods=['POST'])
def start_session():
    """Start active attendance session."""
    if not session.get('admin_logged_in'):
        flash('Unauthorized. Please log in first.', 'error')
        return redirect(url_for('admin'))
        
    subject = request.form.get('subject')
    section = request.form.get('section')
    
    if not subject or not section:
        flash('Subject and Section are required.', 'error')
        return redirect(url_for('admin'))
        
    success, res = SessionManager.start_session(subject, section)
    if success:
        flash(f"Session started for {subject} ({section}).", "success")
        return redirect(url_for('index'))
    else:
        flash(res, "error")
        return redirect(url_for('admin'))

@app.route('/admin/session/stop', methods=['POST'])
def stop_session():
    """Stop and finalize current session."""
    success, res = SessionManager.stop_session()
    if success:
        flash("Session finalized successfully and written to index.", "success")
    else:
        flash(res, "error")
    return redirect(url_for('admin'))

@app.route('/admin/session/delete', methods=['POST'])
def remove_session():
    """Delete a past session record and CSV file."""
    if not session.get('admin_logged_in'):
        flash('Unauthorized.', 'error')
        return redirect(url_for('admin'))
        
    session_id = request.form.get('session_id')
    if delete_session(session_id):
        flash('Session deleted successfully.', 'success')
    else:
        flash('Session deletion failed.', 'error')
    return redirect(url_for('admin'))

@app.route('/admin/attendance/override', methods=['POST'])
def attendance_override():
    """Manual override for marking a student present or absent."""
    roll_number = request.form.get('roll_number')
    action = request.form.get('action') # 'present' or 'absent'
    
    active_sess = SessionManager.get_active_session()
    if not active_sess:
        return jsonify({"success": False, "message": "No active session."}), 400
        
    # Check if student is registered
    students = load_students()
    student = next((s for s in students if s['roll_number'] == roll_number), None)
    if not student:
        return jsonify({"success": False, "message": "Student not found."}), 404
        
    if action == 'present':
        success, record = SessionManager.mark_attendance(
            roll_number=roll_number,
            name=student['name'],
            confidence_score=1.0, # 100% confidence for manual override
            method='manual_override',
            override_by='Admin'
        )
        return jsonify({"success": success, "message": "Marked present."})
    elif action == 'absent':
        success, msg = SessionManager.mark_absent_override(roll_number)
        return jsonify({"success": success, "message": msg})
        
    return jsonify({"success": False, "message": "Invalid action."}), 400

@app.route('/admin/register', methods=['GET', 'POST'])
def register():
    """Student registration view and form submission endpoint."""
    if not session.get('admin_logged_in'):
        flash('Unauthorized. Please log in to admin panel to register students.', 'error')
        return redirect(url_for('admin'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        roll_number = request.form.get('roll_number')
        section = request.form.get('section')
        email = request.form.get('email', '')
        consent_given = request.form.get('consent_given')
        
        # Validation checks
        if not name or not roll_number or not section:
            flash('All student fields are required.', 'error')
            return redirect(url_for('register'))
            
        if consent_given != 'yes':
            flash('Consent notice must be accepted under DPDP compliance.', 'error')
            return redirect(url_for('register'))
            
        # Check if roll number already active
        existing_students = load_students()
        if any(s['roll_number'] == roll_number for s in existing_students):
            flash(f"Student with Roll Number {roll_number} is already enrolled.", 'error')
            return redirect(url_for('register'))
            
        uploaded_files = request.files.getlist('photos')
        if len(uploaded_files) < 3 or len(uploaded_files) > 10:
            flash('You must select between 3 to 10 photos.', 'error')
            return redirect(url_for('register'))
            
        # Create temp folder for processing
        temp_dir = os.path.join(config.DATA_DIR, f"temp_{roll_number}")
        os.makedirs(temp_dir, exist_ok=True)
        saved_paths = []
        
        try:
            for idx, file in enumerate(uploaded_files):
                if file and allowed_file(file.filename):
                    ext = secure_filename(file.filename).rsplit('.', 1)[1].lower()
                    filename = f"photo_{idx}.{ext}"
                    filepath = os.path.join(temp_dir, filename)
                    file.save(filepath)
                    saved_paths.append(filepath)
                    
            # Try to build encodings
            success, msg = register_student_encodings(roll_number, saved_paths)
            
            if success:
                # Move photos to final known_faces directory
                student_folder = os.path.join(config.KNOWN_FACES_DIR, f"{name.replace(' ', '_')}_{roll_number}")
                os.makedirs(student_folder, exist_ok=True)
                
                # Copy temp photos to student folder
                final_paths = []
                for idx, path in enumerate(saved_paths):
                    ext = path.rsplit('.', 1)[1]
                    final_path = os.path.join(student_folder, f"photo_{idx}.{ext}")
                    shutil.move(path, final_path)
                    final_paths.append(final_path)
                    
                # Write record to students.csv master
                consent_ip = request.remote_addr or '127.0.0.1'
                write_student_to_master(roll_number, name, section, email, consent_ip, len(final_paths))
                
                # Reload DB in tracking module
                tracker_instance.reload_db()
                flash(msg, 'success')
                return redirect(url_for('admin'))
            else:
                flash(msg, 'error')
                return redirect(url_for('register'))
                
        except Exception as e:
            flash(f"An error occurred during registration: {e}", 'error')
            return redirect(url_for('register'))
        finally:
            # Clean up temp folder
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                
    return render_template('register.html')

@app.route('/admin/students/<roll_number>/delete', methods=['POST'])
def delete_student(roll_number):
    """Soft delete student metadata and clean up face encodings and photos."""
    if not session.get('admin_logged_in'):
        flash('Unauthorized.', 'error')
        return redirect(url_for('admin'))
        
    students = load_students()
    student = next((s for s in students if s['roll_number'] == roll_number), None)
    
    if student:
        # 1. Soft delete in CSV
        soft_delete_student(roll_number)
        # 2. Delete encoding from Pickle DB
        delete_student_encoding(roll_number)
        
        # 3. Clean up photo folders
        name_clean = student['name'].replace(' ', '_')
        folder_path = os.path.join(config.KNOWN_FACES_DIR, f"{name_clean}_{roll_number}")
        if os.path.exists(folder_path):
            try:
                shutil.rmtree(folder_path)
            except Exception as e:
                print(f"Error removing photos folder: {e}")
                
        tracker_instance.reload_db()
        flash(f"Student {student['name']} de-enrolled and biometric data deleted.", 'success')
    else:
        flash("Student not found.", "error")
        
    return redirect(url_for('reports'))

@app.route('/admin/reports')
def reports():
    """Reports main page displaying registration statistics."""
    students = load_students()
    return render_template('reports.html', students=students)

@app.route('/admin/reports/export/<session_id>')
def export_session_csv(session_id):
    """Download individual session CSV file."""
    history = get_session_history()
    target = next((s for s in history if s['session_id'] == session_id), None)
    
    if target and os.path.exists(target['csv_path']):
        filename = os.path.basename(target['csv_path'])
        with open(target['csv_path'], 'r', encoding='utf-8') as f:
            csv_content = f.read()
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename={filename}"}
        )
    else:
        flash("Session file not found.", "error")
        return redirect(url_for('admin'))

@app.route('/admin/reports/weekly/export')
def export_weekly_excel():
    """Compile and download weekly attendance percentages Excel report."""
    output_path = os.path.join(config.DATA_DIR, "weekly_attendance_report.xlsx")
    success, msg = generate_weekly_report_excel(output_path)
    
    if success and os.path.exists(output_path):
        with open(output_path, 'rb') as f:
            excel_content = f.read()
            
        # Delete temporary excel file after loading content
        try:
            os.remove(output_path)
        except Exception:
            pass
            
        return Response(
            excel_content,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-disposition": "attachment; filename=weekly_attendance_report.xlsx"}
        )
    else:
        flash(msg, "error")
        return redirect(url_for('reports'))

if __name__ == '__main__':
    # Disable debug reloader so camera device is initialized once
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
