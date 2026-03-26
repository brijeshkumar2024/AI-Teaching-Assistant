"""
agents/quiz_agent.py
─────────────────────
Adaptive quiz generation agent.
- Generates questions at the right difficulty based on student performance
- Tracks per-student per-topic scores to auto-adjust difficulty
- Validates student answers with detailed explanations
- Supports MCQ, True/False, and short-answer formats
"""

import json
import time
import re
from typing import Dict, List, Optional, Tuple

from core.llm_config import get_llm
from core.memory import save_interaction
from database.models import log_quiz_attempt

# ── Difficulty ladder ─────────────────────────────────────────────────────
DIFFICULTY_LEVELS = ["easy", "medium", "hard"]

# ── Per-student performance tracker ──────────────────────────────────────
# Structure: { (student_id, course_id, topic) : {"correct": int, "total": int} }
_performance: Dict[Tuple, Dict] = {}


# ── Question generation prompts ───────────────────────────────────────────

GENERATE_PROMPT = """You are an expert programming instructor creating a quiz question.

Topic      : {topic}
Difficulty : {difficulty}
Format     : {format}
Course     : {course_id}
Prior context (what student has struggled with): {weak_areas}

Generate exactly ONE quiz question in this JSON format:
{{
  "question"       : "The question text here",
  "format"         : "{format}",
  "options"        : ["A) ...", "B) ...", "C) ...", "D) ..."],
  "correct_answer" : "A",
  "explanation"    : "Why this answer is correct, with a teaching moment",
  "hint"           : "A gentle nudge without giving away the answer",
  "difficulty"     : "{difficulty}",
  "topic"          : "{topic}"
}}

Rules:
- For "mcq"         : provide exactly 4 options, correct_answer is "A", "B", "C", or "D"
- For "true_false"  : options = ["True", "False"], correct_answer is "True" or "False"
- For "short_answer": options = [], correct_answer is a concise expected answer (1-3 words or a value)
- Make questions realistic and practical, not purely theoretical
- Difficulty "easy"   : recall and basic application
- Difficulty "medium" : understanding and moderate application
- Difficulty "hard"   : analysis, edge cases, debugging scenarios
- Return ONLY the JSON object, no markdown, no extra text
"""

EVALUATE_PROMPT = """You are a supportive programming instructor evaluating a student's quiz answer.

Question       : {question}
Correct answer : {correct_answer}
Student answer : {student_answer}
Explanation    : {explanation}

Evaluate the student's answer and respond in this JSON format:
{{
  "is_correct"  : true/false,
  "score"       : 0.0 to 1.0,
  "feedback"    : "Personalised, encouraging feedback explaining correctness",
  "teaching_point" : "One key concept the student should take away"
}}

Rules:
- For short_answer: allow reasonable paraphrasing (score 0.8 if conceptually correct but imprecise)
- Always be encouraging even when wrong
- Feedback must explain WHY the answer is right/wrong — not just state it
- Return ONLY the JSON object, no markdown, no extra text
"""


# ── Performance tracking ──────────────────────────────────────────────────

def _get_performance(student_id: str, course_id: str, topic: str) -> Dict:
    key = (student_id.lower(), course_id.lower(), topic.lower())
    if key not in _performance:
        _performance[key] = {"correct": 0, "total": 0, "streak": 0}
    return _performance[key]


def _update_performance(
    student_id: str, course_id: str, topic: str, is_correct: bool
) -> None:
    perf = _get_performance(student_id, course_id, topic)
    perf["total"] += 1
    if is_correct:
        perf["correct"] += 1
        perf["streak"]  += 1
    else:
        perf["streak"] = 0


def _compute_difficulty(student_id: str, course_id: str, topic: str) -> str:
    """
    Adaptive difficulty:
    - Start at easy
    - Promote to medium after 3 consecutive correct
    - Promote to hard after 3 more consecutive correct
    - Demote one level after 2 consecutive wrong
    """
    perf   = _get_performance(student_id, course_id, topic)
    total  = perf["total"]
    streak = perf["streak"]
    rate   = perf["correct"] / total if total > 0 else 0.0

    if total == 0:
        return "easy"
    if rate >= 0.85 and streak >= 3:
        return "hard"
    if rate >= 0.65 or streak >= 2:
        return "medium"
    return "easy"


def _get_weak_areas(student_id: str, course_id: str) -> str:
    """Returns topics where the student is struggling (< 60% accuracy)."""
    weak = []
    for (sid, cid, topic), perf in _performance.items():
        if sid != student_id.lower() or cid != course_id.lower():
            continue
        if perf["total"] > 0 and (perf["correct"] / perf["total"]) < 0.60:
            weak.append(topic)
    return ", ".join(weak) if weak else "None identified yet"


# ── Core functions ────────────────────────────────────────────────────────

def generate_question(
    student_id : str,
    course_id  : str,
    topic      : str,
    fmt        : str = "mcq",
    difficulty : Optional[str] = None,
    stream: bool = False,
    token_callback=None,
    max_tokens: int = 450,
) -> Dict:
    """
    Generate a single adaptive quiz question.

    Args:
        student_id : Student identifier
        course_id  : Course identifier
        topic      : Programming topic (e.g. "recursion", "loops")
        fmt        : "mcq", "true_false", or "short_answer"
        difficulty : Override auto-difficulty if provided

    Returns:
        Question dict with: question, format, options, correct_answer,
                            explanation, hint, difficulty, topic
    """
    if difficulty is None:
        difficulty = _compute_difficulty(student_id, course_id, topic)

    weak_areas = _get_weak_areas(student_id, course_id)
    llm= get_llm(temperature=0.7)   # slight creativity for variety

    prompt = GENERATE_PROMPT.format(
        topic      = topic,
        difficulty = difficulty,
        format     = fmt,
        course_id  = course_id,
        weak_areas = weak_areas,
    )

    if not stream:
        response = llm.invoke(prompt)
        if hasattr(response, "content"):
            raw = response.content.strip()
        else:
            raw = str(response).strip()
        
    else:
        from langchain_core.messages import HumanMessage
        tokens: List[str] = []
        for chunk in llm.stream([HumanMessage(content=prompt)]):
            token = getattr(chunk, "content", None) or getattr(chunk, "text", "")
            if token:
                tokens.append(token)
                if token_callback:
                    token_callback(token)
        raw = "".join(tokens).strip()

    # Strip markdown fences if LLM wraps in ```json
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        question_data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return a safe default question
        question_data = {
            "question"      : f"What is the main purpose of {topic} in Python?",
            "format"        : "short_answer",
            "options"       : [],
            "correct_answer": "To solve problems efficiently",
            "explanation"   : "This is a fundamental concept in programming.",
            "hint"          : f"Think about what problems {topic} helps solve.",
            "difficulty"    : difficulty,
            "topic"         : topic,
        }

    question_data["student_id"] = student_id
    question_data["course_id"]  = course_id
    return question_data


def evaluate_answer(
    student_id    : str,
    course_id     : str,
    question_data : Dict,
    student_answer: str,
    stream: bool = False,
    token_callback=None,
    max_tokens: int = 500,
) -> Dict:
    """
    Evaluate a student's answer to a quiz question.

    Args:
        student_id     : Student identifier
        course_id      : Course identifier
        question_data  : The question dict from generate_question()
        student_answer : The student's answer string

    Returns:
        {
            "is_correct"     : bool,
            "score"          : float,
            "feedback"       : str,
            "teaching_point" : str,
            "new_difficulty" : str,   # difficulty for next question on this topic
        }
    """
    llm = get_llm(temperature=0.0)

    prompt = EVALUATE_PROMPT.format(
        question       = question_data["question"],
        correct_answer = question_data["correct_answer"],
        student_answer = student_answer,
        explanation    = question_data.get("explanation", ""),
    )

    if not stream:
        response = llm.invoke(prompt)
        raw = response.content.strip()
    else:
        from langchain_core.messages import HumanMessage
        tokens: List[str] = []
        for chunk in llm.stream([HumanMessage(content=prompt)]):
            token = getattr(chunk, "content", None) or getattr(chunk, "text", "")
            if token:
                tokens.append(token)
                if token_callback:
                    token_callback(token)
        raw = "".join(tokens).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        eval_data = json.loads(raw)
    except json.JSONDecodeError:
        is_correct = student_answer.strip().lower() == \
                     question_data["correct_answer"].strip().lower()
        eval_data = {
            "is_correct"     : is_correct,
            "score"          : 1.0 if is_correct else 0.0,
            "feedback"       : "Good attempt! Keep practising." if is_correct else \
                               f"The correct answer is {question_data['correct_answer']}.",
            "teaching_point" : question_data.get("explanation", ""),
        }

    topic      = question_data.get("topic", "general")
    is_correct = eval_data.get("is_correct", False)

    # Update performance tracker
    _update_performance(student_id, course_id, topic, is_correct)

    # Save to memory
    memory_msg = f"[Quiz on '{topic}' ({question_data.get('difficulty','?')})] Q: {question_data['question']}"
    memory_ans = f"Student answered: {student_answer}. {'Correct!' if is_correct else 'Incorrect.'} {eval_data.get('feedback','')}"
    save_interaction(student_id, course_id, memory_msg, memory_ans)

    # Persist quiz attempt to MongoDB (best-effort).
    try:
        log_quiz_attempt(
            student_id=student_id.strip().lower(),
            course_id=course_id.strip().lower(),
            topic=topic,
            difficulty=question_data.get("difficulty", "unknown"),
            question=question_data["question"],
            correct_answer=question_data.get("correct_answer"),
            student_answer=student_answer,
            is_correct=bool(is_correct),
            score=float(eval_data.get("score", 0.0) or 0.0),
        )
    except Exception:
        pass

    eval_data["new_difficulty"] = _compute_difficulty(student_id, course_id, topic)
    eval_data["topic"]          = topic
    return eval_data


def get_student_quiz_summary(student_id: str, course_id: str) -> Dict:
    """
    Returns a full quiz performance summary for a student in a course.
    Used by the instructor dashboard.
    """
    summary = {}
    for (sid, cid, topic), perf in _performance.items():
        if sid != student_id.lower() or cid != course_id.lower():
            continue
        total   = perf["total"]
        correct = perf["correct"]
        summary[topic] = {
            "total"     : total,
            "correct"   : correct,
            "accuracy"  : round(correct / total, 2) if total > 0 else 0.0,
            "difficulty": _compute_difficulty(student_id, course_id, topic),
            "streak"    : perf["streak"],
        }
    return summary


def get_all_quiz_stats(course_id: str) -> Dict:
    """
    Returns aggregated quiz stats for all students in a course.
    Used by the instructor dashboard.
    """
    topic_stats: Dict[str, Dict] = {}
    for (sid, cid, topic), perf in _performance.items():
        if cid != course_id.lower():
            continue
        if topic not in topic_stats:
            topic_stats[topic] = {"total": 0, "correct": 0, "students": set()}
        topic_stats[topic]["total"]    += perf["total"]
        topic_stats[topic]["correct"]  += perf["correct"]
        topic_stats[topic]["students"].add(sid)

    result = {}
    for topic, stats in topic_stats.items():
        result[topic] = {
            "total_attempts"  : stats["total"],
            "accuracy"        : round(stats["correct"] / stats["total"], 2) if stats["total"] > 0 else 0,
            "student_count"   : len(stats["students"]),
        }
    return result


if __name__ == "__main__":
    q = generate_question("alice", "python101", "recursion", fmt="mcq")
    print(f"Question: {q['question']}")
    print(f"Options : {q['options']}")
    print(f"Difficulty: {q['difficulty']}")

    result = evaluate_answer("alice", "python101", q, q["correct_answer"])
    print(f"\nFeedback: {result['feedback']}")
    print(f"Correct : {result['is_correct']}")
    print(f"Next difficulty: {result['new_difficulty']}")