"""
agents/study_plan_agent.py
───────────────────────────
AI-powered personalised study plan generator.
Analyses student's quiz performance, interaction history,
and weak topics to generate a tailored weekly study plan.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Dict, List
from core.llm_config import get_llm


STUDY_PLAN_PROMPT = """You are an expert academic advisor and programming instructor.

Generate a personalised 7-day study plan for this student:

Student: {student_name}
Course : {course_id}
Quiz accuracy    : {quiz_accuracy}%
Weak topics      : {weak_topics}
Strong topics    : {strong_topics}
Total questions  : {total_questions}
Failed submissions: {failed_submissions}
Learning goal    : {goal}

Create a detailed, realistic 7-day plan. Return ONLY valid JSON:
{{
  "student_name" : "{student_name}",
  "course_id"    : "{course_id}",
  "goal"         : "{goal}",
  "summary"      : "2-sentence personalised overview",
  "days": [
    {{
      "day"       : 1,
      "date"      : "Day 1",
      "focus"     : "Topic to focus on",
      "duration"  : "2 hours",
      "tasks"     : [
        "Specific task 1",
        "Specific task 2",
        "Specific task 3"
      ],
      "resources" : "What to read/watch/practice",
      "quiz_topic": "Topic to quiz yourself on"
    }}
  ],
  "tips": ["Tip 1", "Tip 2", "Tip 3"]
}}

Rules:
- Start weak topics early in the week
- Include code practice tasks daily
- Make tasks specific and actionable
- Include quiz practice every 2 days
- Return ONLY the JSON object, no markdown
"""


def generate_study_plan(
    student_id : str,
    course_id  : str,
    goal       : str = "Master the course fundamentals",
    stream: bool = False,
    token_callback=None,
    max_tokens: int = 900,
) -> Dict:
    """
    Generate a personalised 7-day study plan for a student.

    Args:
        student_id : Student identifier
        course_id  : Course identifier
        goal       : Student's learning goal

    Returns:
        Full study plan dict with 7 days of tasks
    """
    # Gather student analytics
    from agents.analytics_agent import _student_metrics
    from agents.quiz_agent      import _performance

    metrics = _student_metrics.get(course_id, {}).get(student_id, {})
    quiz_accuracy    = 0
    weak_topics      = []
    strong_topics    = []

    # Analyse quiz performance per topic
    for (sid, cid, topic), perf in _performance.items():
        if sid != student_id.lower() or cid != course_id.lower():
            continue
        if perf["total"] > 0:
            acc = perf["correct"] / perf["total"]
            if acc < 0.6:
                weak_topics.append(topic)
            else:
                strong_topics.append(topic)

    total_quiz   = metrics.get("quiz_attempts",      0)
    total_correct= metrics.get("quiz_correct",       0)
    quiz_accuracy= round((total_correct/total_quiz)*100, 0) if total_quiz > 0 else 0
    failed_subs  = metrics.get("failed_submissions", 0)

    # Default weak topics if none detected
    if not weak_topics:
        weak_topics = ["recursion", "OOP", "algorithms"]

    name = student_id.replace("_", " ").title()

    llm    = get_llm(temperature=0.6, max_tokens=max_tokens, streaming=stream)
    prompt = STUDY_PLAN_PROMPT.format(
        student_name      = name,
        course_id         = course_id,
        quiz_accuracy     = quiz_accuracy,
        weak_topics       = ", ".join(weak_topics) or "Not enough data yet",
        strong_topics     = ", ".join(strong_topics) or "Still being assessed",
        total_questions   = metrics.get("total_questions", 0),
        failed_submissions= failed_subs,
        goal              = goal,
    )

    if not stream:
        response = llm.invoke(prompt)
        raw = response.content.strip()
    else:
        from langchain_core.messages import HumanMessage
        tokens = []
        for chunk in llm.stream([HumanMessage(content=prompt)]):
            token = getattr(chunk, "content", None) or getattr(chunk, "text", "")
            if token:
                tokens.append(token)
                if token_callback:
                    token_callback(token)
        raw = "".join(tokens).strip()
    raw      = re.sub(r"^```(?:json)?\s*", "", raw)
    raw      = re.sub(r"\s*```$",          "", raw)

    try:
        plan = json.loads(raw)
    except Exception:
        plan = _fallback_plan(name, course_id, weak_topics, goal)

    # Add real dates
    today = datetime.now()
    for i, day in enumerate(plan.get("days", [])):
        date = today + timedelta(days=i)
        day["date"] = date.strftime("%A, %b %d")

    plan["generated_at"] = datetime.utcnow().isoformat()
    plan["weak_topics"]  = weak_topics
    plan["strong_topics"]= strong_topics
    return plan


def _fallback_plan(name: str, course_id: str, weak_topics: list, goal: str) -> Dict:
    """Fallback plan if LLM fails."""
    today = datetime.now()
    days  = []
    topics = (weak_topics + ["functions", "loops", "OOP", "data structures",
                              "algorithms", "exceptions", "files"])[:7]
    for i, topic in enumerate(topics):
        days.append({
            "day"       : i + 1,
            "date"      : (today + timedelta(days=i)).strftime("%A, %b %d"),
            "focus"     : topic.title(),
            "duration"  : "1.5 hours",
            "tasks"     : [
                f"Read notes on {topic}",
                f"Complete 2 practice problems on {topic}",
                f"Quiz yourself on {topic}",
            ],
            "resources" : f"Course notes + online {topic} tutorials",
            "quiz_topic": topic,
        })

    return {
        "student_name": name,
        "course_id"   : course_id,
        "goal"        : goal,
        "summary"     : f"Personalised plan for {name} focusing on {', '.join(weak_topics[:2])}.",
        "days"        : days,
        "tips"        : [
            "Practice coding every day — even 30 minutes helps.",
            "Quiz yourself after each topic to reinforce learning.",
            "Ask the AI tutor whenever you're stuck.",
        ],
    }