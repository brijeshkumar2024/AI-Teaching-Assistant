"""
core/persistent_memory.py
──────────────────────────
MongoDB-backed persistent memory.
Chat history survives page refresh and server restarts.
Falls back to in-memory if MongoDB is unavailable.
"""

import os
from datetime import datetime
from typing import Dict, List, Tuple
from dotenv import load_dotenv

load_dotenv()

MAX_TURNS = int(os.getenv("MAX_MEMORY_TURNS", 20))

# ── In-memory fallback ────────────────────────────────────────────────────
_memory_store: Dict[Tuple, List] = {}

def _is_mongo_connection_failure(exc: Exception) -> bool:
    """
    Heuristic: treat SSL/tls/certificate and connectivity timeouts as failures
    where we can safely fall back to in-memory.
    """
    msg = str(exc).lower()
    return any(
        key in msg
        for key in [
            "tls",
            "ssl",
            "certificate",
            "handshake",
            "serverselectiontimeouterror",
            "timeout",
            "connection",
            "network is unreachable",
        ]
    )


def _get_collection():
    try:
        from database.models import get_collection
        return get_collection("chat_history")
    except Exception:
        return None


def save_interaction(student_id: str, course_id: str, student_message: str, ai_response: str) -> None:
    sid = student_id.strip().lower()
    cid = course_id.strip().lower()

    # Save to MongoDB
    col = _get_collection()
    if col is not None:
        try:
            col.update_one(
                {"student_id": sid, "course_id": cid},
                {"$push": {"messages": {
                    "$each": [
                        {"role": "human", "content": student_message, "ts": datetime.utcnow()},
                        {"role": "ai",    "content": ai_response,     "ts": datetime.utcnow()},
                    ],
                    "$slice": -(MAX_TURNS * 2),
                }}},
                upsert=True,
            )
            return
        except Exception as e:  # noqa: BLE001
            # Only fall back if MongoDB connectivity itself is failing.
            if _is_mongo_connection_failure(e):
                pass
            else:
                raise

    # Fallback to in-memory
    key = (sid, cid)
    if key not in _memory_store:
        _memory_store[key] = []
    _memory_store[key].append({"role": "human", "content": student_message})
    _memory_store[key].append({"role": "ai",    "content": ai_response})
    if len(_memory_store[key]) > MAX_TURNS * 2:
        _memory_store[key] = _memory_store[key][-(MAX_TURNS * 2):]


def get_history_as_text(student_id: str, course_id: str) -> str:
    sid = student_id.strip().lower()
    cid = course_id.strip().lower()

    # Try MongoDB first
    col = _get_collection()
    if col is not None:
        try:
            doc = col.find_one({"student_id": sid, "course_id": cid})
            if doc and doc.get("messages"):
                lines = []
                for m in doc["messages"][-(MAX_TURNS * 2):]:
                    role = "Student" if m["role"] == "human" else "AI Tutor"
                    lines.append(f"{role}: {m['content']}")
                return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            if _is_mongo_connection_failure(e):
                pass
            else:
                raise

    # Fallback
    key = (sid, cid)
    msgs = _memory_store.get(key, [])
    if not msgs:
        return "No prior conversation."
    lines = []
    for m in msgs:
        role = "Student" if m["role"] == "human" else "AI Tutor"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines)


def get_chat_history(student_id: str, course_id: str) -> List[Dict]:
    sid = student_id.strip().lower()
    cid = course_id.strip().lower()
    col = _get_collection()
    if col is not None:
        try:
            doc = col.find_one({"student_id": sid, "course_id": cid})
            if doc:
                return doc.get("messages", [])
        except Exception as e:  # noqa: BLE001
            if _is_mongo_connection_failure(e):
                pass
            else:
                raise
    return _memory_store.get((sid, cid), [])


def clear_memory(student_id: str, course_id: str) -> None:
    sid = student_id.strip().lower()
    cid = course_id.strip().lower()
    col = _get_collection()
    if col is not None:
        try:
            col.delete_one({"student_id": sid, "course_id": cid})
        except Exception as e:  # noqa: BLE001
            if _is_mongo_connection_failure(e):
                pass
            else:
                raise
    _memory_store.pop((sid, cid), None)


def get_student_stats(student_id: str) -> Dict:
    sid = student_id.strip().lower()
    col = _get_collection()
    stats = {}
    if col is not None:
        try:
            for doc in col.find({"student_id": sid}):
                turns = len(doc.get("messages", [])) // 2
                stats[doc["course_id"]] = turns
            return stats
        except Exception:
            pass
    for (s, c), msgs in _memory_store.items():
        if s == sid:
            stats[c] = len(msgs) // 2
    return stats