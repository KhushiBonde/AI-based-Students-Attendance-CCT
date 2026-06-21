import os
import pickle
import numpy as np
import face_recognition
import config

def load_encodings_db():
    """Load the face encodings database from disk."""
    if os.path.exists(config.ENCODINGS_DB_PATH):
        try:
            with open(config.ENCODINGS_DB_PATH, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"Error loading encodings database: {e}")
            return {}
    return {}

def save_encodings_db(db):
    """Save the face encodings database to disk."""
    try:
        with open(config.ENCODINGS_DB_PATH, 'wb') as f:
            pickle.dump(db, f)
        return True
    except Exception as e:
        print(f"Error saving encodings database: {e}")
        return False

def register_student_encodings(roll_number, photo_paths):
    """
    Extract face encodings from list of photos, average them, and save to database.
    Args:
        roll_number (str): Unique student roll number.
        photo_paths (list): List of paths to student's registration photos.
    Returns:
        tuple: (success (bool), message (str))
    """
    encodings = []
    
    for path in photo_paths:
        if not os.path.exists(path):
            continue
        try:
            from PIL import Image, ImageOps
            # Load and auto-rotate image based on EXIF orientation metadata (fixes smartphone portrait photos)
            pil_img = Image.open(path)
            pil_img = ImageOps.exif_transpose(pil_img)
            image = np.array(pil_img.convert('RGB'))
            # Find face locations
            with config.DLIB_LOCK:
                face_locations = face_recognition.face_locations(image, model=config.FACE_DETECTION_MODEL)
            
            if len(face_locations) == 0:
                print(f"Skipping photo {os.path.basename(path)}: No face detected.")
                continue
            elif len(face_locations) > 1:
                print(f"Skipping photo {os.path.basename(path)}: Multiple faces detected.")
                continue
                
            # Generate face encodings
            with config.DLIB_LOCK:
                face_encs = face_recognition.face_encodings(image, face_locations)
            if face_encs:
                encodings.append(face_encs[0])
        except Exception as e:
            print(f"Error processing photo {path}: {e}")
            continue
            
    if len(encodings) < 3:
        return False, f"Failed to encode. Need at least 3 valid photos with single faces (only {len(encodings)} succeeded)."
        
    # Calculate average encoding across all photos for stability
    avg_encoding = np.mean(encodings, axis=0)
    
    # Load existing database, add/update, and save
    db = load_encodings_db()
    db[roll_number] = avg_encoding
    
    if save_encodings_db(db):
        return True, f"Successfully registered face encodings for Roll No: {roll_number} using {len(encodings)} photos."
    else:
        return False, "Failed to save encodings database."

def delete_student_encoding(roll_number):
    """Remove student encoding from the database."""
    db = load_encodings_db()
    if roll_number in db:
        del db[roll_number]
        save_encodings_db(db)
        return True
    return False
