import cv2
import threading
import time
import numpy as np
import face_recognition
import config
from core.encoder import load_encodings_db
from core.attendance import load_students, SessionManager

class VideoTracker:
    def __init__(self):
        self.camera = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        self.last_frame = None
        self.known_encodings = {}
        self.student_map = {}  # roll_number -> name
        
        # Performance/Health metrics
        self.fps = 0
        self.camera_connected = False
        self.frame_count = 0
        self.reload_db()

    def reload_db(self):
        """Reload known face encodings and student details."""
        with self.lock:
            self.known_encodings = load_encodings_db()
            students = load_students()
            self.student_map = {s['roll_number']: s['name'] for s in students}
            print(f"Loaded {len(self.known_encodings)} student encodings for recognition.")
            if self.camera:
                self.camera.release()
                self.camera = None

    def start(self):
        """Start the background tracking thread."""
        if self.running:
            return
        self.running = True
        self.reload_db()
        self.thread = threading.Thread(target=self._run_tracker, daemon=True)
        self.thread.start()
        print("Camera recognition thread started.")

    def stop(self):
        """Stop the background tracking thread and release camera."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        self.release_camera()
        print("Camera recognition thread stopped.")

    def release_camera(self):
        with self.lock:
            if self.camera:
                self.camera.release()
                self.camera = None
            self.camera_connected = False

    def _run_tracker(self):
        """Main camera loop running in background thread."""
        self.frame_count = 0
        
        while self.running:
            # Reconnect camera if disconnected
            if self.camera is None:
                with self.lock:
                    print(f"Connecting to camera index/URL: {config.CAMERA_INDEX}...")
                    self.camera = cv2.VideoCapture(config.CAMERA_INDEX)
                    if self.camera.isOpened():
                        self.camera_connected = True
                        print("Camera connected successfully.")
                    else:
                        self.camera = None
                        self.camera_connected = False
                        print("Failed to open camera. Retrying in 5 seconds...")
                if not self.camera_connected:
                    # Generate a placeholder frame indicating camera disconnected
                    self._generate_error_frame("Camera Disconnected. Reconnecting...")
                    time.sleep(5)
                    continue

            # Read frame
            ret, frame = self.camera.read()
            if not ret:
                print("Failed to grab frame from camera.")
                self.release_camera()
                continue
                
            self.frame_count += 1
            
            # Processing interval guard
            if self.frame_count % config.RECOGNITION_INTERVAL == 0:
                self._process_frame(frame)
            else:
                # For non-processed frames, we draw the last known bounding boxes on the new frame to prevent flickering
                self._annotate_and_store_frame(frame, reuse_boxes=True)
                
            time.sleep(0.01) # Small sleep to yield CPU

    def _process_frame(self, frame):
        """Perform face detection and recognition on the frame."""
        # 1. Resize frame to 1/4 size for faster processing
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        # Convert BGR (OpenCV) to RGB (face_recognition)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
        
        # 2. Find faces in the frame
        with config.DLIB_LOCK:
            face_locations = face_recognition.face_locations(rgb_small_frame, model=config.FACE_DETECTION_MODEL)
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)
        
        face_names = []
        face_confidences = []
        
        # 3. Check if there are active sessions
        active_session = SessionManager.get_active_session()
        
        with self.lock:
            known_rolls = list(self.known_encodings.keys())
            known_vectors = list(self.known_encodings.values())
            
        for face_encoding in face_encodings:
            name = "Unknown"
            roll = "Unknown"
            confidence = 0.0
            
            if known_vectors:
                # Compute distances
                distances = face_recognition.face_distance(known_vectors, face_encoding)
                if len(distances) > 0:
                    min_dist_idx = np.argmin(distances)
                    min_dist = distances[min_dist_idx]
                    
                    if min_dist < config.RECOGNITION_THRESHOLD:
                        roll = known_rolls[min_dist_idx]
                        name = self.student_map.get(roll, roll)
                        confidence = round(1.0 - min_dist, 2)
                        
                        # Mark Attendance if a session is running
                        if active_session and active_session['section'] == self._get_student_section(roll):
                            SessionManager.mark_attendance(
                                roll_number=roll, 
                                name=name, 
                                confidence_score=confidence, 
                                method='auto'
                            )
                            
            face_names.append((name, roll))
            face_confidences.append(confidence)
            
        # Store detections for overlay drawing
        self.last_detections = {
            'locations': face_locations,
            'names': face_names,
            'confidences': face_confidences
        }
        
        self._annotate_and_store_frame(frame, reuse_boxes=False)

    def _get_student_section(self, roll_number):
        """Helper to get student's section from students list."""
        students = load_students()
        for s in students:
            if s['roll_number'] == roll_number:
                return s['section']
        return None

    def _annotate_and_store_frame(self, frame, reuse_boxes=False):
        """Draw bounding boxes and details on the frame and cache it."""
        if not hasattr(self, 'last_detections') or not self.last_detections:
            with self.lock:
                self.last_frame = frame.copy()
            return
            
        detections = self.last_detections
        locations = detections['locations']
        names = detections['names']
        confidences = detections['confidences']
        
        annotated_frame = frame.copy()
        
        for (top, right, bottom, left), (name, roll), confidence in zip(locations, names, confidences):
            # Scale face locations back up by 4 since we shrunked it
            top *= 4
            right *= 4
            bottom *= 4
            left *= 4
            
            # Choose color: Emerald Green for recognized, Soft Red for Unknown
            is_known = roll != "Unknown"
            color = (46, 204, 113) if is_known else (82, 82, 252) # BGR: Green vs Soft Red/Orange
            
            # Draw bounding box
            cv2.rectangle(annotated_frame, (left, top), (right, bottom), color, 2)
            
            # Draw label background
            label = f"{name} ({confidence*100:.0f}%)" if is_known else "Unknown"
            font = cv2.FONT_HERSHEY_DUPLEX
            label_size, base_line = cv2.getTextSize(label, font, 0.6, 1)
            
            cv2.rectangle(
                annotated_frame, 
                (left, top - label_size[1] - 10), 
                (left + label_size[0] + 10, top), 
                color, 
                cv2.FILLED
            )
            # Text inside bounding box label
            cv2.putText(
                annotated_frame, 
                label, 
                (left + 5, top - 7), 
                font, 
                0.6, 
                (255, 255, 255), 
                1, 
                cv2.LINE_AA
            )
            
        # Draw live status banner (indicates if a session is currently recording)
        active_session = SessionManager.get_active_session()
        if active_session:
            banner_text = f"REC ACTIVE: {active_session['subject']} ({active_session['section']})"
            cv2.rectangle(annotated_frame, (10, 10), (320, 40), (46, 204, 113), cv2.FILLED)
            cv2.putText(
                annotated_frame, 
                banner_text, 
                (20, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 
                0.5, 
                (255, 255, 255), 
                1, 
                cv2.LINE_AA
            )
            
        with self.lock:
            self.last_frame = annotated_frame

    def _generate_error_frame(self, message):
        """Creates a black frame with an error message overlay."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(
            frame, 
            message, 
            (100, 240), 
            cv2.FONT_HERSHEY_SIMPLEX, 
            0.7, 
            (82, 82, 252), 
            2, 
            cv2.LINE_AA
        )
        with self.lock:
            self.last_frame = frame

    def get_frame_jpeg(self):
        """Returns the latest frame encoded as JPEG bytes."""
        with self.lock:
            if self.last_frame is None:
                # Make empty black frame
                self._generate_error_frame("Initializing video capture...")
            
            ret, jpeg = cv2.imencode('.jpg', self.last_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret:
                return jpeg.tobytes()
        return None

# Global instance
tracker_instance = VideoTracker()
