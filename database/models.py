"""
database/models.py
──────────────────
MongoDB database layer using PyMongo.
Collections:
  - students         : registered students
  - courses          : available courses
  - interactions     : every student–AI conversation turn
  - code_submissions : code review requests + feedback
  - quiz_attempts    : quiz question attempts + scores
  - at_risk_flags    : instructor alerts for struggling students
No ORM needed — MongoDB uses flexible documents.
"""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database

load_dotenv()

# ── Connection ────────────────────────────────────────────────────────────
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB  = os.getenv("MONGODB_DB",  "ai_teaching_assistant")

_client: Optional[MongoClient] = None
_db    : Optional[Database]    = None


def get_db() -> Database:
    """Returns the MongoDB database instance (singleton)."""
    global _client, _db
    if _db is None:
        _client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            tls=True,
            tlsAllowInvalidCertificates=True,
        )
        _db     = _client[MONGODB_DB]
    return _db


def get_collection(name: str) -> Collection:
    """Returns a MongoDB collection by name."""
    return get_db()[name]


# ── Index setup ───────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create all collections and indexes.
    Safe to call multiple times — MongoDB ignores duplicate index creation.
    """
    db = get_db()

    # students
    db.students.create_index("student_id", unique=True)
    db.students.create_index("email")
    # legacy auth collection used by `core/auth.py`
    db.students_auth.create_index("student_id", unique=True)

    # courses
    db.courses.create_index("course_id", unique=True)

    # interactions
    db.interactions.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)])
    db.interactions.create_index("created_at")
    db.interactions.create_index("interaction_type")

    # chat_history (persistent memory)
    db.chat_history.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)])
    db.chat_history.create_index("student_id")
    db.chat_history.create_index("course_id")

    # code_submissions
    db.code_submissions.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)])
    db.code_submissions.create_index("fingerprint")
    db.code_submissions.create_index("created_at")

    # quiz_attempts
    db.quiz_attempts.create_index([("student_id", ASCENDING), ("course_id", ASCENDING)])
    db.quiz_attempts.create_index("topic")

    # at_risk_flags
    db.at_risk_flags.create_index([("student_id", ASCENDING), ("resolved", ASCENDING)])
    db.at_risk_flags.create_index("severity")

    print(f"[MongoDB] Indexes created on database '{MONGODB_DB}'")


# ── Student helpers ───────────────────────────────────────────────────────

def upsert_student(student_id: str, name: str, email: str = None) -> None:
    """Insert or update a student document."""
    get_collection("students").update_one(
        {"student_id": student_id},
        {"$set": {
            "student_id" : student_id,
            "name"       : name,
            "email"      : email,
            "updated_at" : datetime.utcnow(),
        }, "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True,
    )


def upsert_course(course_id: str, name: str, description: str = "") -> None:
    """Insert or update a course document."""
    get_collection("courses").update_one(
        {"course_id": course_id},
        {"$set": {
            "course_id"  : course_id,
            "name"       : name,
            "description": description,
            "is_active"  : True,
            "updated_at" : datetime.utcnow(),
        }, "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True,
    )


# ── Interaction logging ───────────────────────────────────────────────────

def log_interaction(
    student_id       : str,
    course_id        : str,
    interaction_type : str,
    student_message  : str,
    ai_response      : str,
    topics           : List[str] = None,
    response_time_ms : int       = None,
) -> str:
    """
    Log a single student–AI interaction turn to MongoDB.
    Returns the inserted document ID as a string.
    """
    doc = {
        "student_id"      : student_id,
        "course_id"       : course_id,
        "interaction_type": interaction_type,   # "qa", "code_review", "quiz", "voice"
        "student_message" : student_message,
        "ai_response"     : ai_response,
        "topics_detected" : topics or [],
        "response_time_ms": response_time_ms,
        "helpful_rating"  : None,               # updated later from student feedback
        "created_at"      : datetime.utcnow(),
    }
    result = get_collection("interactions").insert_one(doc)
    return str(result.inserted_id)


# ── Code submission logging ───────────────────────────────────────────────

def log_code_submission(
    student_id        : str,
    course_id         : str,
    code              : str,
    execution_output  : str  = None,
    execution_passed  : bool = None,
    ai_feedback       : str  = None,
    plagiarism_score  : float = 0.0,
    ai_generated_flag : bool  = False,
    fingerprint       : str  = None,
    language          : str  = "python",
) -> str:
    """Log a code submission and its review result."""
    doc = {
        "student_id"       : student_id,
        "course_id"        : course_id,
        "code"             : code,
        "language"         : language,
        "execution_output" : execution_output,
        "execution_passed" : execution_passed,
        "ai_feedback"      : ai_feedback,
        "plagiarism_score" : plagiarism_score,
        "ai_generated_flag": ai_generated_flag,
        "fingerprint"      : fingerprint,
        "created_at"       : datetime.utcnow(),
    }
    result = get_collection("code_submissions").insert_one(doc)
    return str(result.inserted_id)


# ── Quiz attempt logging ──────────────────────────────────────────────────

def log_quiz_attempt(
    student_id     : str,
    course_id      : str,
    topic          : str,
    difficulty     : str,
    question       : str,
    correct_answer : str,
    student_answer : str  = None,
    is_correct     : bool = None,
    score          : float = 0.0,
) -> str:
    """Log a single quiz attempt."""
    doc = {
        "student_id"    : student_id,
        "course_id"     : course_id,
        "topic"         : topic,
        "difficulty"    : difficulty,
        "question"      : question,
        "correct_answer": correct_answer,
        "student_answer": student_answer,
        "is_correct"    : is_correct,
        "score"         : score,
        "created_at"    : datetime.utcnow(),
    }
    result = get_collection("quiz_attempts").insert_one(doc)
    return str(result.inserted_id)


# ── At-risk flag logging ──────────────────────────────────────────────────

def log_at_risk_flag(
    student_id : str,
    course_id  : str,
    reason     : str,
    severity   : str = "medium",
) -> str:
    """Log an at-risk flag for a student."""
    doc = {
        "student_id" : student_id,
        "course_id"  : course_id,
        "reason"     : reason,
        "severity"   : severity,
        "resolved"   : False,
        "created_at" : datetime.utcnow(),
        "resolved_at": None,
    }
    result = get_collection("at_risk_flags").insert_one(doc)
    return str(result.inserted_id)


def resolve_at_risk_flag(flag_id: str) -> None:
    """Mark an at-risk flag as resolved."""
    from bson import ObjectId
    get_collection("at_risk_flags").update_one(
        {"_id": ObjectId(flag_id)},
        {"$set": {"resolved": True, "resolved_at": datetime.utcnow()}},
    )


# ── Analytics queries ─────────────────────────────────────────────────────

def get_student_interaction_count(student_id: str, course_id: str) -> int:
    return get_collection("interactions").count_documents(
        {"student_id": student_id, "course_id": course_id}
    )


def get_course_interaction_count(course_id: str) -> int:
    return get_collection("interactions").count_documents({"course_id": course_id})


def get_topic_frequency(course_id: str) -> Dict[str, int]:
    """Aggregates topic frequency across all interactions in a course."""
    pipeline = [
        {"$match" : {"course_id": course_id}},
        {"$unwind": "$topics_detected"},
        {"$group" : {"_id": "$topics_detected", "count": {"$sum": 1}}},
        {"$sort"  : {"count": DESCENDING}},
    ]
    results = get_collection("interactions").aggregate(pipeline)
    return {r["_id"]: r["count"] for r in results if r["_id"]}


def get_student_quiz_accuracy(student_id: str, course_id: str) -> float:
    """Returns overall quiz accuracy for a student in a course."""
    pipeline = [
        {"$match": {"student_id": student_id, "course_id": course_id, "is_correct": {"$ne": None}}},
        {"$group": {"_id": None,
                    "total"  : {"$sum": 1},
                    "correct": {"$sum": {"$cond": ["$is_correct", 1, 0]}}}},
    ]
    result = list(get_collection("quiz_attempts").aggregate(pipeline))
    if not result or result[0]["total"] == 0:
        return 0.0
    return round(result[0]["correct"] / result[0]["total"], 2)


def get_recent_interactions(course_id: str, limit: int = 100) -> List[Dict]:
    """Returns the most recent interactions for a course."""
    return list(
        get_collection("interactions")
        .find({"course_id": course_id}, {"_id": 0})
        .sort("created_at", DESCENDING)
        .limit(limit)
    )


def get_unresolved_at_risk(course_id: str) -> List[Dict]:
    """Returns all unresolved at-risk flags for a course."""
    return list(
        get_collection("at_risk_flags")
        .find({"course_id": course_id, "resolved": False}, {"_id": 0})
        .sort("severity", ASCENDING)
    )


if __name__ == "__main__":
    try:
        init_db()
        upsert_student("alice", "Alice Smith", "alice@university.edu")
        upsert_course("python101", "Introduction to Python", "Beginner Python course")
        log_interaction("alice", "python101", "qa", "What is recursion?",
                        "Recursion is when a function calls itself...", ["recursion"], 420)
        print(f"[MongoDB] Test write successful.")
        print(f"[MongoDB] Interaction count: {get_course_interaction_count('python101')}")
    except Exception as e:
        print(f"[MongoDB] Connection failed: {e}")
        print("Make sure MongoDB is running: mongod --dbpath ./data/db")