import os

# Base directory of the project
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Data storage paths
if os.environ.get('RENDER') == 'true':
    PERSISTENT_DIR = "/opt/render/persistent"
    # Check if we have write access to the persistent volume mount (Paid Tier)
    try:
        os.makedirs(PERSISTENT_DIR, exist_ok=True)
        # Test write permission
        test_file = os.path.join(PERSISTENT_DIR, ".write_test")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        # Use persistent storage
        DATA_DIR = os.path.join(PERSISTENT_DIR, "data")
        KNOWN_FACES_DIR = os.path.join(PERSISTENT_DIR, "known_faces")
    except Exception:
        # Fall back to local project folder (Free Tier - ephemeral)
        DATA_DIR = os.path.join(BASE_DIR, "data")
        KNOWN_FACES_DIR = os.path.join(BASE_DIR, "known_faces")
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
    KNOWN_FACES_DIR = os.path.join(BASE_DIR, "known_faces")

ENCODINGS_DB_PATH = os.path.join(DATA_DIR, "encodings_db.pkl")
STUDENTS_CSV_PATH = os.path.join(DATA_DIR, "students.csv")
ATTENDANCE_DIR = os.path.join(DATA_DIR, "attendance")

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

