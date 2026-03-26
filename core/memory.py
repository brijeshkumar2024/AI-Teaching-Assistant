"""
core/memory.py
──────────────
Per-student, per-course conversation memory.
Pure Python implementation — no langchain.memory dependency.
Works with all langchain versions.
"""

import os
from typing import Dict, List, Tuple
from dotenv import load_dotenv

load_dotenv()

MAX_TURNS = int(os.getenv("MAX_MEMORY_TURNS", 20))

# ── Simple message store ──────────────────────────────────────────────────
# Structure: (student_id, course_id) → list of {"role": "human"|"ai", "content": str}
_memory_store: Dict[Tuple[str, str], List[Dict]] = {}


def _make_key(student_id: str, course_id: str) -> Tuple[str, str]:
    return (student_id.strip().lower(), course_id.strip().lower())


def get_memory(student_id: str, course_id: str) -> List[Dict]:
    """Returns the message list for a student in a course."""
    key = _make_key(student_id, course_id)
    if key not in _memory_store:
        _memory_store[key] = []
    return _memory_store[key]


def save_interaction(
    student_id: str,
    course_id: str,
    student_message: str,
    ai_response: str,
) -> None:
    """Save a single turn to memory."""
    key = _make_key(student_id, course_id)
    if key not in _memory_store:
        _memory_store[key] = []

    _memory_store[key].append({"role": "human", "content": student_message})
    _memory_store[key].append({"role": "ai",    "content": ai_response})

    # Keep only the last MAX_TURNS * 2 messages
    max_msgs = MAX_TURNS * 2
    if len(_memory_store[key]) > max_msgs:
        _memory_store[key] = _memory_store[key][-max_msgs:]


def get_chat_history(student_id: str, course_id: str) -> List[Dict]:
    """Returns full message history as list of dicts."""
    return get_memory(student_id, course_id)


def get_history_as_text(student_id: str, course_id: str) -> str:
    """Returns conversation history as plain text for prompt injection."""
    messages = get_memory(student_id, course_id)
    if not messages:
        return "No prior conversation."
    lines = []
    for msg in messages:
        role = "Student" if msg["role"] == "human" else "AI Tutor"
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


def get_history_as_langchain_messages(student_id: str, course_id: str) -> List:
    """Returns history as LangChain message objects for prompt templates."""
    from langchain_core.messages import HumanMessage, AIMessage
    messages = get_memory(student_id, course_id)
    result = []
    for msg in messages:
        if msg["role"] == "human":
            result.append(HumanMessage(content=msg["content"]))
        else:
            result.append(AIMessage(content=msg["content"]))
    return result


def clear_memory(student_id: str, course_id: str) -> None:
    """Clears memory for a specific student-course pair."""
    key = _make_key(student_id, course_id)
    if key in _memory_store:
        _memory_store[key] = []


def clear_all_memory() -> None:
    """Clears all memory."""
    _memory_store.clear()


def get_student_stats(student_id: str) -> Dict[str, int]:
    """Returns turn counts per course for a student."""
    stats = {}
    for (sid, cid), msgs in _memory_store.items():
        if sid == student_id.strip().lower():
            stats[cid] = len(msgs) // 2
    return stats


if __name__ == "__main__":
    save_interaction("alice", "python101", "What is recursion?", "Recursion is when a function calls itself...")
    save_interaction("alice", "python101", "Give me an example.", "Fibonacci is a classic example...")
    print(get_history_as_text("alice", "python101"))
    print(f"Stats: {get_student_stats('alice')}")