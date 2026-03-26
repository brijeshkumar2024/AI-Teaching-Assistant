"""
core/auth.py
─────────────
Student authentication system.
Register, login, and session management backed by MongoDB.
Passwords are hashed with bcrypt.
Falls back gracefully if MongoDB is unavailable.
"""

import os
import hashlib
import secrets
import traceback
from datetime import datetime
from typing import Optional, Dict
from dotenv import load_dotenv

load_dotenv()


def _hash_password(password: str, salt: str = None) -> tuple:
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return hashed, salt


def _get_collection():
    try:
        from database.models import get_collection
        return get_collection("students_auth")
    except Exception:
        return None


# ── In-memory fallback ────────────────────────────────────────────────────
_users: Dict[str, Dict] = {}


def register_student(
    student_id : str,
    name       : str,
    password   : str,
    email      : str = "",
    course_id  : str = "",
) -> Dict:
    """
    Register a new student account.
    Returns {"success": bool, "message": str, "student_id": str}
    """
    sid = student_id.strip().lower().replace(" ", "_")

    # Check if already exists
    existing = get_student(sid)
    if existing:
        return {"success": False, "message": "Student ID already exists. Please login instead."}

    hashed, salt = _hash_password(password)
    doc = {
        "student_id": sid,
        "name"      : name.strip(),
        "email"     : email.strip(),
        "password"  : hashed,
        "salt"      : salt,
        "course_id" : course_id,
        "created_at": datetime.utcnow(),
        "last_login": None,
        "total_sessions": 0,
    }

    col = _get_collection()
    if col is not None:
        try:
            col.insert_one(doc)
            return {"success": True, "message": "Account created!", "student_id": sid}
        except Exception as e:
            if "duplicate" in str(e).lower():
                return {"success": False, "message": "Student ID already taken."}

    # Fallback
    _users[sid] = doc
    return {"success": True, "message": "Account created!", "student_id": sid}


def login_student(student_id: str, password: str) -> Dict:
    """
    Authenticate a student.
    Returns {"success": bool, "message": str, "student": dict|None}
    """
    sid = student_id.strip().lower().replace(" ", "_")
    student = get_student(sid)

    if not student:
        return {"success": False, "message": "Account not found. Please register first.", "student": None}

    salt = student.get("salt")
    stored_hash = student.get("password")
    if not salt or not stored_hash:
        return {
            "success": False,
            "message": "Account credentials are missing or corrupted.",
            "student": None,
        }

    hashed, _ = _hash_password(password, salt)
    if hashed != stored_hash:
        return {"success": False, "message": "Incorrect password.", "student": None}

    # Update last login
    col = _get_collection()
    if col is not None:
        try:
            col.update_one(
                {"student_id": sid},
                {"$set"  : {"last_login": datetime.utcnow()},
                 "$inc"  : {"total_sessions": 1}}
            )
        except Exception:
            pass
    else:
        if sid in _users:
            _users[sid]["last_login"]     = datetime.utcnow()
            _users[sid]["total_sessions"] += 1

    return {"success": True, "message": f"Welcome back, {student['name']}!", "student": student}


def get_student(student_id: str) -> Optional[Dict]:
    """Fetch student record by ID."""
    sid = student_id.strip().lower().replace(" ", "_")
    col = _get_collection()
    if col is not None:
        try:
            doc = col.find_one({"student_id": sid}, {"_id": 0})
            return doc
        except Exception:
            pass
    return _users.get(sid)


def update_student_course(student_id: str, course_id: str) -> None:
    """Update the active course for a student."""
    sid = student_id.strip().lower().replace(" ", "_")
    col = _get_collection()
    if col is not None:
        try:
            col.update_one({"student_id": sid}, {"$set": {"course_id": course_id}})
            return
        except Exception:
            pass
    if sid in _users:
        _users[sid]["course_id"] = course_id


def get_all_students(course_id: str = None) -> list:
    """Get all registered students, optionally filtered by course."""
    col = _get_collection()
    query = {"course_id": course_id} if course_id else {}
    if col is not None:
        try:
            return list(col.find(query, {"_id": 0, "password": 0, "salt": 0}))
        except Exception:
            pass
    students = list(_users.values())
    if course_id:
        students = [s for s in students if s.get("course_id") == course_id]
    return students
