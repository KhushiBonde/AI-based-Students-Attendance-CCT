import os
import shutil
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd
import config

# Temporary test directories
TEST_DATA_DIR = os.path.join(config.BASE_DIR, "test_data")
config.DATA_DIR = TEST_DATA_DIR
config.ENCODINGS_DB_PATH = os.path.join(TEST_DATA_DIR, "test_encodings_db.pkl")
config.STUDENTS_CSV_PATH = os.path.join(TEST_DATA_DIR, "test_students.csv")
config.ATTENDANCE_DIR = os.path.join(TEST_DATA_DIR, "test_attendance")
config.KNOWN_FACES_DIR = os.path.join(TEST_DATA_DIR, "test_known_faces")

from core.attendance import (
    initialize_files, load_students, write_student_to_master, soft_delete_student,
    SessionManager, get_session_history, generate_weekly_report_excel
)
from core.encoder import register_student_encodings, load_encodings_db

class TestAttendanceSystem(unittest.TestCase):
    
    def setUp(self):
        # Create temp folder structures
        os.makedirs(TEST_DATA_DIR, exist_ok=True)
        os.makedirs(config.ATTENDANCE_DIR, exist_ok=True)
        os.makedirs(config.KNOWN_FACES_DIR, exist_ok=True)
        initialize_files()

    def tearDown(self):
        # Cleanup
        if os.path.exists(TEST_DATA_DIR):
            shutil.rmtree(TEST_DATA_DIR)
            
        # Ensure session resets
        SessionManager._active_session = None

    def test_student_registration_and_soft_delete(self):
        # Write student
        write_student_to_master(
            roll_number="12345",
            name="Alice Smith",
            section="CSE-A",
            email="alice@test.com",
            consent_ip="192.168.1.1",
            photo_count=3
        )
        
        students = load_students()
        self.assertEqual(len(students), 1)
        self.assertEqual(students[0]['name'], "Alice Smith")
        self.assertEqual(students[0]['consent_given'], "True")
        self.assertEqual(students[0]['consent_ip'], "192.168.1.1")
        
        # Soft delete
        success = soft_delete_student("12345")
        self.assertTrue(success)
        
        # Active only should return 0
        students_active = load_students(active_only=True)
        self.assertEqual(len(students_active), 0)
        
        # Inactive check
        students_all = load_students(active_only=False)
        self.assertEqual(len(students_all), 1)
        self.assertEqual(students_all[0]['active'], "False")

    @patch('PIL.Image.open')
    @patch('PIL.ImageOps.exif_transpose')
    @patch('face_recognition.face_locations')
    @patch('face_recognition.face_encodings')
    def test_student_encoding_pipeline(self, mock_enc, mock_loc, mock_exif, mock_open):
        # Mock face recognition to return dummy 128-dim vectors
        from PIL import Image
        dummy_img = Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8))
        mock_open.return_value = dummy_img
        mock_exif.return_value = dummy_img
        mock_loc.return_value = [(10, 20, 30, 40)]
        mock_enc.return_value = [np.ones(128)]
        
        photo_paths = ["p1.jpg", "p2.jpg", "p3.jpg"]
        for p in photo_paths:
            with open(os.path.join(TEST_DATA_DIR, p), "w") as f:
                f.write("dummy")
                
        success, msg = register_student_encodings("12345", [os.path.join(TEST_DATA_DIR, p) for p in photo_paths])
        self.assertTrue(success)
        
        # Load encoding DB to check
        db = load_encodings_db()
        self.assertIn("12345", db)
        self.assertEqual(db["12345"].shape, (128,))
        np.testing.assert_array_equal(db["12345"], np.ones(128))

    def test_session_lifecycle_and_attendance(self):
        # Register student in master first
        write_student_to_master("999", "Bob", "CSE-B", "bob@test.com", "127.0.0.1", 3)
        
        # Start Session
        success, sess = SessionManager.start_session("Data Science", "CSE-B")
        self.assertTrue(success)
        self.assertEqual(sess['subject'], "Data Science")
        self.assertEqual(sess['section'], "CSE-B")
        self.assertEqual(sess['total_enrolled'], 1)
        
        # Mark present
        success, rec = SessionManager.mark_attendance("999", "Bob", 0.85, method="auto")
        self.assertTrue(success)
        self.assertEqual(rec['roll_number'], "999")
        self.assertEqual(rec['confidence_score'], 0.85)
        self.assertEqual(rec['method'], "auto")
        
        # Test Duplicate Guard
        success_dup, msg_dup = SessionManager.mark_attendance("999", "Bob", 0.90, method="auto")
        self.assertFalse(success_dup)
        self.assertEqual(msg_dup, "Already marked present.")
        
        # Test manual override (absent)
        success_abs, msg_abs = SessionManager.mark_absent_override("999")
        self.assertTrue(success_abs)
        self.assertNotIn("999", SessionManager.get_active_session()['records'])
        
        # Test manual override (present)
        success_pres, rec_pres = SessionManager.mark_attendance("999", "Bob", 1.0, method="manual_override")
        self.assertTrue(success_pres)
        self.assertEqual(rec_pres['method'], "manual_override")
        
        # Stop Session
        success_stop, stop_entry = SessionManager.stop_session()
        self.assertTrue(success_stop)
        self.assertEqual(stop_entry['total_present'], 1)
        
        # Verify Session Index in history
        history = get_session_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['subject'], "Data Science")

    def test_weekly_report_excel_generation(self):
        # Mock active student and session data
        write_student_to_master("101", "Alice", "CSE-A", "alice@test.com", "127.0.0.1", 3)
        write_student_to_master("102", "Charlie", "CSE-A", "charlie@test.com", "127.0.0.1", 3)
        
        # Create session 1 (Alice present, Charlie absent)
        SessionManager.start_session("Math", "CSE-A")
        SessionManager.mark_attendance("101", "Alice", 0.9, method="auto")
        SessionManager.stop_session()
        
        # Create session 2 (Alice present, Charlie absent)
        SessionManager.start_session("Math", "CSE-A")
        SessionManager.mark_attendance("101", "Alice", 0.9, method="auto")
        SessionManager.stop_session()
        
        output_excel = os.path.join(TEST_DATA_DIR, "weekly_report_test.xlsx")
        success, msg = generate_weekly_report_excel(output_excel)
        
        self.assertTrue(success)
        self.assertTrue(os.path.exists(output_excel))
        
        # Read Excel using pandas
        df = pd.read_excel(output_excel)
        # Alice attended 2/2 -> 100%
        # Charlie attended 0/2 -> 0%
        alice_row = df[df['Roll Number'] == 101].iloc[0]
        charlie_row = df[df['Roll Number'] == 102].iloc[0]
        
        self.assertEqual(alice_row['Attendance %'], 100.0)
        self.assertEqual(charlie_row['Attendance %'], 0.0)

if __name__ == '__main__':
    unittest.main()
