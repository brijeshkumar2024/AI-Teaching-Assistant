"""
agents/analytics_agent.py
──────────────────────────
Student analytics and at-risk detection agent.
Tracks:
  - Question frequency heatmaps per topic
  - Per-student interaction patterns
  - At-risk detection via rule-based thresholds + LLM reasoning
  - Weekly summary generation for instructors
  - Common misconception extraction
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from core.llm_config import get_llm
from core.memory import get_chat_history, get_student_stats
from database.models import get_collection

# ── In-memory analytics store ─────────────────────────────────────────────
# All stores are keyed by course_id, then student_id

_interaction_log: Dict[str, List[Dict]] = defaultdict(list)   # course → [events]
_student_metrics: Dict[str, Dict[str, Dict]] = defaultdict(   # course → student → metrics
    lambda: defaultdict(lambda: {
        "total_questions"      : 0,
        "code_submissions"     : 0,
        "quiz_attempts"        : 0,
        "quiz_correct"         : 0,
        "failed_submissions"   : 0,
        "repeated_topics"      : defaultdict(int),
        "last_active"          : None,
        "session_count"        : 0,
        "avg_response_helpful" : [],
    })
)

# ── At-risk thresholds ────────────────────────────────────────────────────
AT_RISK_RULES = {
    "high_question_volume"    : 15,    # >15 questions/day = struggling
    "low_quiz_accuracy"       : 0.40,  # <40% quiz accuracy
    "repeated_topic_threshold": 4,     # same topic asked 4+ times
    "failed_submissions"      : 3,     # 3+ failed code submissions
    "inactive_days"           : 3,     # no activity for 3+ days
}


# ── Log ingestion ─────────────────────────────────────────────────────────

def log_event(
    course_id        : str,
    student_id       : str,
    event_type       : str,   # "qa", "code_review", "quiz", "voice"
    topic            : str,
    success          : bool  = True,
    extra            : Dict  = None,
) -> None:
    """
    Record a single student interaction event.
    Called by all other agents after each interaction.
    """
    event = {
        "student_id" : student_id,
        "event_type" : event_type,
        "topic"      : topic,
        "success"    : success,
        "timestamp"  : datetime.utcnow().isoformat(),
        "extra"      : extra or {},
    }
    _interaction_log[course_id].append(event)

    # Update student metrics
    m = _student_metrics[course_id][student_id]
    m["last_active"] = datetime.utcnow()

    if event_type == "qa":
        m["total_questions"] += 1
        m["repeated_topics"][topic] += 1
    elif event_type == "code_review":
        m["code_submissions"] += 1
        if not success:
            m["failed_submissions"] += 1
    elif event_type == "quiz":
        m["quiz_attempts"] += 1
        if success:
            m["quiz_correct"] += 1


# ── MongoDB-backed dashboard analytics ─────────────────────────────────────

_SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3}


def _cid(course_id: str) -> str:
    return (course_id or "").strip().lower()


def _student_recommendation_from_flags(flags: List[Dict]) -> str:
    rules = {f.get("rule") for f in flags}
    if "low_quiz_accuracy" in rules:
        return "Focus on the fundamentals behind weak quiz topics. Give one short, guided walkthrough + 3 practice questions."
    if "failed_submissions" in rules:
        return "Switch to debugging-focused practice: ask for failing test output, then guide the student through fixing one bug at a time."
    if "repeated_topic" in rules or "repeated_topic_threshold" in rules:
        return "Review the repeatedly misunderstood concept with a targeted example and a quick check for understanding."
    if "inactive_days" in rules:
        return "Send a friendly reminder and suggest a simple ‘start here’ mini-lesson to reduce friction."
    if "high_question_volume" in rules:
        return "Offer structured support: recommend a learning plan + cap distractions by prioritizing the top 1–2 weak topics."
    return "Schedule a 1:1 check-in and offer a focused next step."


def _get_student_metrics_from_mongo(course_id: str) -> Dict[str, Dict]:
    """
    Returns per-student metrics needed by the dashboard:
      - total_questions (qa interactions)
      - quiz_attempts, quiz_correct, quiz_accuracy
      - code_submissions, failed_submissions
      - last_active (from interactions.max(created_at))
    """
    cid = _cid(course_id)
    interactions = get_collection("interactions")
    quiz_attempts = get_collection("quiz_attempts")
    code_submissions = get_collection("code_submissions")
    students_auth = get_collection("students_auth")
    chat_history = get_collection("chat_history")

    # Questions count + last activity (all interaction types, but questions only for qa)
    q_rows = list(
        interactions.aggregate(
            [
                {"$match": {"course_id": cid}},
                {
                    "$group": {
                        "_id": "$student_id",
                        "total_questions": {
                            "$sum": {"$cond": [{"$eq": ["$interaction_type", "qa"]}, 1, 0]}
                        },
                        "last_active": {"$max": "$created_at"},
                    }
                },
            ]
        )
    )
    questions_map = {
        r["_id"]: {"total_questions": int(r.get("total_questions", 0)), "last_active": r.get("last_active")}
        for r in q_rows
        if r.get("_id") is not None
    }

    # Last activity fallback from persistent chat history.
    chat_rows = list(
        chat_history.aggregate(
            [
                {"$match": {"course_id": cid}},
                {"$unwind": "$messages"},
                {"$group": {"_id": "$student_id", "last_chat_activity": {"$max": "$messages.ts"}}},
            ]
        )
    )
    chat_last_map = {r["_id"]: r.get("last_chat_activity") for r in chat_rows if r.get("_id") is not None}

    # Quiz stats
    quiz_rows = list(
        quiz_attempts.aggregate(
            [
                {"$match": {"course_id": cid, "is_correct": {"$ne": None}}},
                {
                    "$group": {
                        "_id": "$student_id",
                        "quiz_attempts": {"$sum": 1},
                        "quiz_correct": {
                            "$sum": {"$cond": [{"$eq": ["$is_correct", True]}, 1, 0]}
                        },
                    }
                },
            ]
        )
    )
    quiz_map = {
        r["_id"]: {"quiz_attempts": int(r.get("quiz_attempts", 0)), "quiz_correct": int(r.get("quiz_correct", 0))}
        for r in quiz_rows
        if r.get("_id") is not None
    }

    # Code submission counts
    code_rows = list(
        code_submissions.aggregate(
            [
                {"$match": {"course_id": cid}},
                {
                    "$group": {
                        "_id": "$student_id",
                        "code_submissions": {"$sum": 1},
                        "failed_submissions": {
                            "$sum": {"$cond": [{"$eq": ["$execution_passed", False]}, 1, 0]}
                        },
                    }
                },
            ]
        )
    )
    code_map = {
        r["_id"]: {"code_submissions": int(r.get("code_submissions", 0)), "failed_submissions": int(r.get("failed_submissions", 0))}
        for r in code_rows
        if r.get("_id") is not None
    }

    registered_ids = set(students_auth.distinct("student_id", {"course_id": cid}))
    student_ids = registered_ids | set(questions_map.keys()) | set(quiz_map.keys()) | set(code_map.keys())
    metrics: Dict[str, Dict] = {}

    for sid in student_ids:
        qm = questions_map.get(sid, {"total_questions": 0, "last_active": None})
        z  = quiz_map.get(sid, {"quiz_attempts": 0, "quiz_correct": 0})
        cm = code_map.get(sid, {"code_submissions": 0, "failed_submissions": 0})

        total_q = int(qm.get("total_questions", 0))
        quiz_attempts_n = int(z.get("quiz_attempts", 0))
        quiz_correct_n = int(z.get("quiz_correct", 0))
        code_sub_n = int(cm.get("code_submissions", 0))
        failed_sub_n = int(cm.get("failed_submissions", 0))

        quiz_accuracy = round(quiz_correct_n / quiz_attempts_n, 2) if quiz_attempts_n > 0 else 0.0

        metrics[sid] = {
            "total_questions": total_q,
            "quiz_attempts": quiz_attempts_n,
            "quiz_correct": quiz_correct_n,
            "quiz_accuracy": quiz_accuracy,
            "code_submissions": code_sub_n,
            "failed_submissions": failed_sub_n,
            "last_active": max(
                [t for t in [qm.get("last_active"), chat_last_map.get(sid)] if t is not None],
                default=None,
            ),
        }

    return metrics


def _get_student_repeated_topics_from_mongo(course_id: str) -> Dict[str, Dict[str, int]]:
    """
    Returns:
      { student_id: { topic: count } }
    based on qa interactions and interactions.topics_detected occurrences.
    """
    cid = _cid(course_id)
    interactions = get_collection("interactions")

    rows = list(
        interactions.aggregate(
            [
                {"$match": {"course_id": cid, "interaction_type": "qa", "topics_detected": {"$exists": True}}},
                {"$unwind": "$topics_detected"},
                {"$match": {"topics_detected": {"$ne": None, "$ne": ""}}},
                {
                    "$group": {
                        "_id": {"student_id": "$student_id", "topic": "$topics_detected"},
                        "count": {"$sum": 1},
                    }
                },
            ]
        )
    )

    repeated: Dict[str, Dict[str, int]] = defaultdict(dict)
    for r in rows:
        sid = r["_id"]["student_id"]
        topic = r["_id"]["topic"]
        repeated[sid][topic] = int(r.get("count", 0))
    return repeated


def refresh_at_risk_flags(course_id: str) -> None:
    """
    Computes at-risk flags from MongoDB and writes them into `at_risk_flags`.
    This removes the need for in-memory demo analytics.
    """
    cid = _cid(course_id)
    at_col = get_collection("at_risk_flags")
    now = datetime.utcnow()

    # Resolve previous unresolved flags (keep history)
    at_col.update_many(
        {"course_id": cid, "resolved": False},
        {"$set": {"resolved": True, "resolved_at": now}},
    )

    student_metrics = _get_student_metrics_from_mongo(cid)
    repeated_topics = _get_student_repeated_topics_from_mongo(cid)

    docs_to_insert: List[Dict] = []
    for sid, m in student_metrics.items():
        flags: List[Dict] = []

        # High question volume
        if m["total_questions"] > AT_RISK_RULES["high_question_volume"]:
            flags.append(
                {
                    "reason": f"Asked {m['total_questions']} questions — may be overwhelmed.",
                    "severity": "medium",
                    "rule": "high_question_volume",
                }
            )

        # Low quiz accuracy
        if m["quiz_attempts"] >= 3:
            if m["quiz_accuracy"] < AT_RISK_RULES["low_quiz_accuracy"]:
                flags.append(
                    {
                        "reason": f"Quiz accuracy is {m['quiz_accuracy']:.0%} ({m['quiz_correct']}/{m['quiz_attempts']}).",
                        "severity": "high",
                        "rule": "low_quiz_accuracy",
                    }
                )

        # Repeated topics
        for topic, count in repeated_topics.get(sid, {}).items():
            if count >= AT_RISK_RULES["repeated_topic_threshold"]:
                flags.append(
                    {
                        "reason": f"Asked about '{topic}' {count} times — persistent confusion.",
                        "severity": "medium",
                        "rule": "repeated_topic",
                    }
                )

        # Failed submissions
        if m["failed_submissions"] >= AT_RISK_RULES["failed_submissions"]:
            flags.append(
                {
                    "reason": f"{m['failed_submissions']} failed code submissions.",
                    "severity": "high",
                    "rule": "failed_submissions",
                }
            )

        # Inactivity
        last_active = m.get("last_active")
        if last_active:
            days_inactive = (now - last_active).days
            if days_inactive >= AT_RISK_RULES["inactive_days"]:
                flags.append(
                    {
                        "reason": f"No activity for {days_inactive} days.",
                        "severity": "low",
                        "rule": "inactive_days",
                    }
                )

        if not flags:
            continue

        last_active_iso = last_active.isoformat() if last_active else None
        for f in flags:
            docs_to_insert.append(
                {
                    "student_id": sid,
                    "course_id": cid,
                    "reason": f["reason"],
                    "severity": f["severity"],
                    "resolved": False,
                    "created_at": now,
                    "resolved_at": None,
                    "rule": f.get("rule"),
                    "last_active": last_active_iso,
                }
            )

    if docs_to_insert:
        at_col.insert_many(docs_to_insert)


def _get_at_risk_students_from_mongo(course_id: str) -> List[Dict]:
    cid = _cid(course_id)
    at_col = get_collection("at_risk_flags")

    docs = list(
        at_col.find(
            {"course_id": cid, "resolved": False},
            {"_id": 0},
        )
    )

    grouped: Dict[str, Dict] = {}
    for d in docs:
        sid = d.get("student_id")
        if not sid:
            continue
        if sid not in grouped:
            grouped[sid] = {
                "student_id": sid,
                "severity": d.get("severity", "low"),
                "flags": [],
                "recommendation": "",
                "last_activity": d.get("last_active"),
            }
        grouped[sid]["flags"].append({"reason": d.get("reason", ""), "rule": d.get("rule")})
        if _SEVERITY_ORDER.get(d.get("severity", "low"), 0) > _SEVERITY_ORDER.get(
            grouped[sid]["severity"], 0
        ):
            grouped[sid]["severity"] = d.get("severity", "low")

        # Keep the most recent last_active if multiple flags exist
        if d.get("last_active") and (not grouped[sid].get("last_activity") or d["last_active"] > grouped[sid]["last_activity"]):
            grouped[sid]["last_activity"] = d["last_active"]

    # Add recommendation after grouping
    for sid, payload in grouped.items():
        payload["recommendation"] = _student_recommendation_from_flags(payload["flags"])

    return sorted(
        grouped.values(),
        key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["severity"], 3),
    )


def _mongo_get_topic_heatmap(course_id: str, top_n: int = 15) -> Dict[str, int]:
    """
    MongoDB-backed topic heatmap.
    Counts occurrences of topics_detected in `interactions` for interaction_type='qa'.
    """
    cid = _cid(course_id)
    interactions = get_collection("interactions")

    rows = list(
        interactions.aggregate(
            [
                {"$match": {"course_id": cid, "interaction_type": "qa", "topics_detected": {"$exists": True}}},
                {"$unwind": "$topics_detected"},
                {"$match": {"topics_detected": {"$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$topics_detected", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": top_n},
            ]
        )
    )
    return {r["_id"]: int(r.get("count", 0)) for r in rows if r.get("_id")}


def _mongo_extract_misconceptions(course_id: str, top_n: int = 5) -> List[Dict]:
    """
    MongoDB-backed misconception extraction (heuristic, no extra LLM calls).

    A misconception candidate is a topic that appears in at least 2 QA interactions
    per student, then grouped across students.
    """
    cid = _cid(course_id)
    interactions = get_collection("interactions")

    # topic occurrences >= 2 per student -> aggregate across students
    rows = list(
        interactions.aggregate(
            [
                {"$match": {"course_id": cid, "interaction_type": "qa", "topics_detected": {"$exists": True}}},
                {"$unwind": "$topics_detected"},
                {"$match": {"topics_detected": {"$ne": None, "$ne": ""}}},
                {"$group": {"_id": {"student_id": "$student_id", "topic": "$topics_detected"}, "count": {"$sum": 1}}},
                {"$match": {"count": {"$gte": 2}}},
                {"$group": {"_id": "$_id.topic", "frequency": {"$sum": "$count"}}},
                {"$sort": {"frequency": -1}},
                {"$limit": top_n},
            ]
        )
    )

    misconceptions = []
    for r in rows:
        topic = r["_id"]
        freq = int(r.get("frequency", 0))
        pretty = str(topic).replace("_", " ").title()
        misconceptions.append(
            {
                "topic": topic,
                "misconception": f"Persistent confusion around {pretty} (repeated topic mentions per student).",
                "frequency": freq,
                "fix": f"Revisit {pretty} with a concrete example, then run a short guided practice to confirm understanding.",
            }
        )

    return misconceptions


def _mongo_generate_weekly_summary(course_id: str) -> str:
    """
    MongoDB-backed weekly summary (data from interactions/at_risk_flags/misconceptions).
    """
    cid = _cid(course_id)
    student_metrics = _get_student_metrics_from_mongo(cid)
    total_students = len(student_metrics)

    interactions = get_collection("interactions")
    total_events = interactions.count_documents({"course_id": cid})

    heatmap = get_topic_heatmap(cid, top_n=5)
    top_topics = list(heatmap.items())
    misconceptions = extract_misconceptions(cid, top_n=3)

    # Ensure at-risk flags exist
    at_col = get_collection("at_risk_flags")
    if at_col.count_documents({"course_id": cid, "resolved": False}) == 0:
        refresh_at_risk_flags(cid)
    at_risk_students = _get_at_risk_students_from_mongo(cid)

    llm = get_llm(temperature=0.4)
    prompt = f"""You are an AI academic assistant writing a weekly course report for an instructor.

Course       : {cid}
Week ending  : {datetime.utcnow().strftime('%B %d, %Y')}
Total interactions    : {total_events}
Active students       : {total_students}
Top topics asked     : {top_topics}
At-risk students     : {len(at_risk_students)}
Common misconceptions : {json.dumps(misconceptions[:3], indent=2)}

Write a professional 3-paragraph weekly summary:
1. Overall course engagement and activity
2. Key learning challenges and misconceptions observed
3. Students needing attention and recommended instructor actions

Be concise, data-driven, and actionable. Use a professional but warm tone.
"""
    try:
        response = llm.invoke(prompt)
        return response.content.strip()
    except Exception:
        return (
            f"Weekly summary for {cid}: {total_events} total interactions across {total_students} students. "
            f"Top topics: {top_topics}. "
            f"At-risk students: {len(at_risk_students)}. "
            f"Misconceptions observed: {json.dumps(misconceptions[:3], ensure_ascii=False) if misconceptions else 'None'}."
        )


# ── At-risk detection ─────────────────────────────────────────────────────

def _rule_based_flags(student_id: str, course_id: str) -> List[Dict]:
    """Returns list of rule-based at-risk flags for a student."""
    m     = _student_metrics[course_id][student_id]
    flags = []

    # High question volume
    if m["total_questions"] > AT_RISK_RULES["high_question_volume"]:
        flags.append({
            "reason"  : f"Asked {m['total_questions']} questions — may be overwhelmed.",
            "severity": "medium",
            "rule"    : "high_question_volume",
        })

    # Low quiz accuracy
    if m["quiz_attempts"] >= 3:
        accuracy = m["quiz_correct"] / m["quiz_attempts"]
        if accuracy < AT_RISK_RULES["low_quiz_accuracy"]:
            flags.append({
                "reason"  : f"Quiz accuracy is {accuracy:.0%} ({m['quiz_correct']}/{m['quiz_attempts']}).",
                "severity": "high",
                "rule"    : "low_quiz_accuracy",
            })

    # Repeated topics
    for topic, count in m["repeated_topics"].items():
        if count >= AT_RISK_RULES["repeated_topic_threshold"]:
            flags.append({
                "reason"  : f"Asked about '{topic}' {count} times — persistent confusion.",
                "severity": "medium",
                "rule"    : "repeated_topic",
            })

    # Failed submissions
    if m["failed_submissions"] >= AT_RISK_RULES["failed_submissions"]:
        flags.append({
            "reason"  : f"{m['failed_submissions']} failed code submissions in a row.",
            "severity": "high",
            "rule"    : "failed_submissions",
        })

    # Inactivity
    if m["last_active"]:
        days_inactive = (datetime.utcnow() - m["last_active"]).days
        if days_inactive >= AT_RISK_RULES["inactive_days"]:
            flags.append({
                "reason"  : f"No activity for {days_inactive} days.",
                "severity": "low",
                "rule"    : "inactivity",
            })

    return flags


def check_at_risk(student_id: str, course_id: str) -> Dict:
    """
    Full at-risk assessment: rule-based + LLM reasoning.

    Returns:
        {
            "is_at_risk"      : bool,
            "severity"        : "low" | "medium" | "high" | "none",
            "flags"           : list,
            "llm_summary"     : str,
            "recommendation"  : str,
        }
    """
    flags = _rule_based_flags(student_id, course_id)

    if not flags:
        return {
            "is_at_risk"    : False,
            "severity"      : "none",
            "flags"         : [],
            "llm_summary"   : "Student appears to be on track.",
            "recommendation": "No action needed.",
        }

    # Determine highest severity
    severity_order = {"low": 1, "medium": 2, "high": 3}
    max_severity   = max(flags, key=lambda f: severity_order.get(f["severity"], 0))["severity"]

    # LLM generates a human-readable summary + recommendation
    llm    = get_llm(temperature=0.2)
    m      = _student_metrics[course_id][student_id]
    prompt = f"""You are an academic advisor reviewing a student's performance data.

Student ID   : {student_id}
Course       : {course_id}
Issues found :
{json.dumps(flags, indent=2)}

Student metrics:
- Total questions asked : {m['total_questions']}
- Code submissions      : {m['code_submissions']}
- Quiz accuracy         : {(m['quiz_correct']/m['quiz_attempts']):.0%} if {m['quiz_attempts']} > 0 else N/A
- Top repeated topics   : {dict(sorted(m['repeated_topics'].items(), key=lambda x: -x[1])[:3])}

Write a concise 2-sentence summary of this student's situation and ONE specific, actionable recommendation for the instructor.
Format:
SUMMARY: ...
RECOMMENDATION: ...
"""
    response = llm.invoke(prompt)
    text     = response.content.strip()

    llm_summary     = re.search(r"SUMMARY:\s*(.+?)(?=RECOMMENDATION:|$)", text, re.DOTALL)
    recommendation  = re.search(r"RECOMMENDATION:\s*(.+)", text, re.DOTALL)

    return {
        "is_at_risk"    : True,
        "severity"      : max_severity,
        "flags"         : flags,
        "llm_summary"   : llm_summary.group(1).strip() if llm_summary else text,
        "recommendation": recommendation.group(1).strip() if recommendation else "Schedule a 1:1 check-in.",
    }


# ── Topic heatmap ─────────────────────────────────────────────────────────

def get_topic_heatmap(course_id: str, top_n: int = 15) -> Dict[str, int]:
    """
    MongoDB-backed topic heatmap.
    Counts occurrences of topics_detected in `interactions` for interaction_type='qa'.
    """
    cid = _cid(course_id)
    interactions = get_collection("interactions")

    rows = list(
        interactions.aggregate(
            [
                {"$match": {"course_id": cid, "interaction_type": "qa", "topics_detected": {"$exists": True}}},
                {"$unwind": "$topics_detected"},
                {"$match": {"topics_detected": {"$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$topics_detected", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": top_n},
            ]
        )
    )
    return {r["_id"]: int(r.get("count", 0)) for r in rows if r.get("_id")}


# ── Common misconceptions ─────────────────────────────────────────────────

def extract_misconceptions(course_id: str, top_n: int = 5) -> List[Dict]:
    """
    MongoDB-backed misconception extraction (heuristic, no extra LLM calls).

    A misconception candidate is a topic that appears in at least 2 QA interactions
    per student, then grouped across students.
    """
    cid = _cid(course_id)
    interactions = get_collection("interactions")

    rows = list(
        interactions.aggregate(
            [
                {"$match": {"course_id": cid, "interaction_type": "qa", "topics_detected": {"$exists": True}}},
                {"$unwind": "$topics_detected"},
                {"$match": {"topics_detected": {"$ne": None, "$ne": ""}}},
                {"$group": {"_id": {"student_id": "$student_id", "topic": "$topics_detected"}, "count": {"$sum": 1}}},
                {"$match": {"count": {"$gte": 2}}},
                {"$group": {"_id": "$_id.topic", "frequency": {"$sum": "$count"}}},
                {"$sort": {"frequency": -1}},
                {"$limit": top_n},
            ]
        )
    )

    misconceptions = []
    for r in rows:
        topic = r["_id"]
        freq = int(r.get("frequency", 0))
        pretty = str(topic).replace("_", " ").title()
        misconceptions.append(
            {
                "topic": topic,
                "misconception": f"Persistent confusion around {pretty} (repeated topic mentions per student).",
                "frequency": freq,
                "fix": f"Revisit {pretty} with a concrete example, then run a short guided practice to confirm understanding.",
            }
        )

    return misconceptions


# ── Weekly summary ────────────────────────────────────────────────────────

def generate_weekly_summary(course_id: str) -> str:
    """
    MongoDB-backed weekly summary report for the instructor.
    """
    cid = _cid(course_id)
    student_metrics = _get_student_metrics_from_mongo(cid)
    total_students = len(student_metrics)

    interactions = get_collection("interactions")
    total_events = interactions.count_documents({"course_id": cid})

    heatmap = get_topic_heatmap(cid, top_n=5)
    top_topics = list(heatmap.items())
    misconceptions = extract_misconceptions(cid, top_n=3)

    # Ensure at-risk flags exist
    at_col = get_collection("at_risk_flags")
    if at_col.count_documents({"course_id": cid, "resolved": False}) == 0:
        refresh_at_risk_flags(cid)

    at_risk_students = _get_at_risk_students_from_mongo(cid)

    llm = get_llm(temperature=0.4)
    prompt = f"""You are an AI academic assistant writing a weekly course report for an instructor.

Course       : {cid}
Week ending  : {datetime.utcnow().strftime('%B %d, %Y')}
Total interactions    : {total_events}
Active students       : {total_students}
Top topics asked     : {top_topics}
At-risk students     : {[(s['student_id'], s['severity']) for s in at_risk_students]}
Common misconceptions : {json.dumps(misconceptions[:3], indent=2)}

Write a professional 3-paragraph weekly summary:
1. Overall course engagement and activity
2. Key learning challenges and misconceptions observed
3. Students needing attention and recommended instructor actions

Be concise, data-driven, and actionable. Use a professional but warm tone.
"""
    try:
        response = llm.invoke(prompt)
        return response.content.strip()
    except Exception:
        return (
            f"Weekly summary for {cid}: {total_events} total interactions across {total_students} students. "
            f"Top topics: {top_topics}. At-risk students: {len(at_risk_students)}."
        )


# ── Dashboard data bundle ─────────────────────────────────────────────────

def get_dashboard_data(course_id: str) -> Dict:
    """
    Returns all analytics data needed for the instructor dashboard in one call.
    """
    cid = _cid(course_id)
    interactions = get_collection("interactions")
    total_interactions = interactions.count_documents({"course_id": cid})

    student_metrics = _get_student_metrics_from_mongo(cid)
    total_students = len(student_metrics)

    topic_heatmap = get_topic_heatmap(cid)

    # Ensure at-risk flags exist
    at_col = get_collection("at_risk_flags")
    if at_col.count_documents({"course_id": cid, "resolved": False}) == 0:
        refresh_at_risk_flags(cid)

    at_risk_students = _get_at_risk_students_from_mongo(cid)
    misconceptions = extract_misconceptions(cid)

    # Keep dashboard-compatible shape
    return {
        "course_id": cid,
        "total_students": total_students,
        "total_interactions": int(total_interactions),
        "topic_heatmap": topic_heatmap,
        "at_risk_students": at_risk_students,
        "misconceptions": misconceptions,
        "student_metrics": {
            sid: {
                "total_questions": m.get("total_questions", 0),
                "code_submissions": m.get("code_submissions", 0),
                "quiz_attempts": m.get("quiz_attempts", 0),
                "quiz_accuracy": m.get("quiz_accuracy", 0.0),
                "failed_submissions": m.get("failed_submissions", 0),
            }
            for sid, m in student_metrics.items()
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":
    # Lightweight sanity check (does not insert demo data).
    cid = "python101"
    print("=== Dashboard data ===")
    data = get_dashboard_data(cid)
    print(f"Students : {data['total_students']}")
    print(f"At-risk  : {len(data['at_risk_students'])}")