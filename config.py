import os

# Base directory of the project
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Data storage paths
DATA_DIR = os.path.join(BASE_DIR, "data")
ENCODINGS_DB_PATH = os.path.join(DATA_DIR, "encodings_db.pkl")
STUDENTS_CSV_PATH = os.path.join(DATA_DIR, "students.csv")
ATTENDANCE_DIR = os.path.join(DATA_DIR, "attendance")
KNOWN_FACES_DIR = os.path.join(BASE_DIR, "known_faces")

# Create directories if they do not exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ATTENDANCE_DIR, exist_ok=True)
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)

# Face Recognition Settings
RECOGNITION_THRESHOLD = 0.60  # Default threshold (Euclidean distance, lower is more strict)
RECOGNITION_INTERVAL = 3      # Process every Nth frame
FACE_DETECTION_MODEL = "hog"  # "hog" for CPU, "cnn" for GPU

# Camera Settings
CAMERA_INDEX = 0              # 0 for default webcam, or an RTSP URL for CCTV camera

# Security Settings
ADMIN_PASSWORD = "admin123"   # Simple password for LAN prototype admin panel
SECRET_KEY = "attendance-secret-key"

import threading
# Global lock to synchronize face_recognition / dlib execution across threads to prevent hard C++ crashes
DLIB_LOCK = threading.Lock()

