"""
agents/quiz_set_agent.py
─────────────────────────
Auto-generates full quiz sets directly from uploaded PDF content.
Generates 5-10 questions covering different topics from the course material.
"""

import json
import re
import time
from typing import Any, List, Dict, Optional
from core.llm_config import get_llm
from core.embeddings import get_retriever
from core.json_utils import parse_quiz_json
from database.models import log_quiz_attempt


QUIZ_SET_PROMPT = """You are an expert programming instructor creating a clean multiple‑choice quiz.

Course material context:
{context}

Write exactly {count} questions at {difficulty_label} difficulty.
Return ONLY valid JSON with this shape — no prose, no markdown fences:
{{
  "questions": [
    {{
      "question": "Concise question text",
      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
      "answer": "A",
      "difficulty": "{difficulty}"
    }}
  ]
}}

Rules:
- Keep options short (<=12 words) and mutually exclusive.
- Do NOT include explanations, hints, or extra keys.
- Use letter answers (A/B/C/D) that exactly match the option prefix.
- If you cannot answer, return {{"questions":[]}}.
"""


def generate_quiz_set_from_pdf(
    course_id  : str,
    topic      : str = None,
    count      : int = 8,
    difficulty : str = "mixed",
    stream: bool = False,
    token_callback=None,
    max_tokens: int = 900,
) -> Dict:
    """
    Generate a full quiz set from course PDF material.

    Args:
        course_id  : Course to pull material from
        topic      : Optional specific topic to focus on
        count      : Number of questions (default 8)
        difficulty : "easy", "medium", "hard", or "mixed"

    Returns:
        {
            "questions"   : list of question dicts,
            "total"       : int,
            "course_id"   : str,
            "topic"       : str,
            "generated_at": str,
        }
    """
    from datetime import datetime

    try:
        # Retrieve relevant context from FAISS
        try:
            retriever = get_retriever(course_id, top_k=8)
            query     = topic or "programming concepts covered in this course"
            docs      = retriever.invoke(query)
            context   = "\n\n---\n\n".join([d.page_content[:500] for d in docs])
        except FileNotFoundError:
            context = (
                "General Python programming concepts including loops, functions, recursion, OOP, and data structures."
            )

        if not context.strip():
            context = "General Python programming concepts."

        llm    = get_llm(temperature=0.4, max_tokens=max_tokens, streaming=stream)
        prompt = QUIZ_SET_PROMPT.format(
            context          = context[:3000],
            count            = max(1, min(10, count)),
            difficulty       = "hard" if difficulty == "hard" else "easy" if difficulty == "easy" else "mixed",
            difficulty_label = difficulty if difficulty != "mixed" else "mixed (balanced)",
        )

        raw = ""
        parsed = None
        error: Optional[str] = None

        def _try_parse(text: str) -> Optional[Dict]:
            nonlocal error
            try:
                return parse_quiz_json(text, expected_count=count)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                return None

        # Two-pass attempt: initial prompt, then stricter retry if needed.
        for attempt in range(2):
            if not stream:
                response = llm.invoke(prompt if attempt == 0 else prompt + "\nReturn STRICT JSON only.")
                raw = response.content.strip()
            else:
                from langchain_core.messages import HumanMessage
                tokens = []
                for chunk in llm.stream(
                    [HumanMessage(content=prompt if attempt == 0 else prompt + "\nSTRICT JSON.")]
                ):
                    token = getattr(chunk, "content", None) or getattr(chunk, "text", "")
                    if token:
                        tokens.append(token)
                        if token_callback:
                            token_callback(token)
                raw = "".join(tokens).strip()

            parsed = _try_parse(raw)
            if parsed:
                break
            time.sleep(0.5)

        if not parsed:
            # Fallback questions if parsing fails
            questions = _fallback_questions(topic or "Python", count, difficulty)
        else:
            # Defensive: parsed["questions"] should be primitives, but coerce any odd items
            # (e.g., Pydantic models) into plain dicts.
            questions = parsed.get("questions", [])
            # Filter by difficulty if requested (difficulty is optional in schema)
            if difficulty != "mixed":
                original_questions = questions

                def _qdiff(item: Any) -> Optional[str]:
                    if isinstance(item, dict):
                        v = item.get("difficulty")
                        return str(v).lower().strip() if isinstance(v, str) and v.strip() else v
                    if hasattr(item, "model_dump"):
                        try:
                            v = item.model_dump().get("difficulty")
                            return (
                                str(v).lower().strip() if isinstance(v, str) and v.strip() else v
                            )
                        except Exception:
                            return None
                    if hasattr(item, "dict"):
                        try:
                            v = item.dict().get("difficulty")
                            return (
                                str(v).lower().strip() if isinstance(v, str) and v.strip() else v
                            )
                        except Exception:
                            return None
                    return None

                questions = [q for q in original_questions if _qdiff(q) == difficulty]
                questions = questions or original_questions

        # Keep output minimal for UI: strip difficulty key to match strict schema
        def _coerce_question(q: Any) -> Dict[str, Any]:
            if isinstance(q, dict):
                return q
            if hasattr(q, "model_dump"):
                try:
                    return q.model_dump()
                except Exception:
                    return {}
            if hasattr(q, "dict"):
                try:
                    return q.dict()
                except Exception:
                    return {}
            return {}

        clean_questions: List[Dict[str, Any]] = []
        for q in questions[:count]:
            qd = _coerce_question(q)
            clean_questions.append(
                {
                    "question": str(qd.get("question", "")).strip(),
                    "options": [
                        str(o).strip()
                        for o in (qd.get("options", []) or [])
                        if str(o).strip()
                    ][:4],
                    "answer": str(qd.get("answer", "")).strip(),
                }
            )

        return {
            "questions"   : clean_questions,
            "total"       : len(clean_questions),
            "course_id"   : course_id,
            "topic"       : topic or "Course Material",
            "generated_at": datetime.utcnow().isoformat(),
            "error"       : error if not parsed else None,
        }
    except Exception as exc:  # noqa: BLE001
        # Never allow Quiz Set generation to crash the UI.
        questions = _fallback_questions(topic or "Python", count, difficulty)
        return {
            "questions": questions,
            "total": len(questions),
            "course_id": course_id,
            "topic": topic or "Course Material",
            "generated_at": datetime.utcnow().isoformat(),
            "error": str(exc),
        }


def _fallback_questions(topic: str, count: int, difficulty: str) -> List[Dict]:
    """Returns varied fallback questions if LLM parsing fails."""
    templates = [
        (
            f"What is the primary purpose of {topic}?",
            [
                "A) To slow programs down",
                "B) To solve problems efficiently",
                "C) To store random values",
                "D) To remove comments",
            ],
            "B",
        ),
        (
            f"Name one real-world task where {topic} is especially useful.",
            [
                "A) Automating repetitive tasks",
                "B) Writing novels automatically",
                "C) Drawing only",
                "D) Random guessing",
            ],
            "A",
        ),
        (
            f"Give a short definition of {topic}.",
            [
                "A) A Python keyword only",
                f"B) A tool/technique to solve programming tasks",
                "C) A hardware device",
                "D) An operating system",
            ],
            "B",
        ),
        (
            f"List one advantage of using {topic}.",
            [
                "A) Improves developer productivity",
                "B) Always increases code size",
                "C) Forces slower execution",
                "D) Eliminates variables",
            ],
            "A",
        ),
        (
            f"What is a common beginner mistake with {topic}?",
            [
                "A) Incorrect syntax or missing setup",
                "B) Writing perfect code",
                "C) Never using variables",
                "D) Only commenting code",
            ],
            "A",
        ),
    ]

    questions: List[Dict] = []
    for i in range(min(count, len(templates))):
        q, options, answer = templates[i]
        questions.append({
            "question": f"[{difficulty}] {q}",
            "options" : options,
            "answer"  : answer,
        })

    # If caller asked for more than our templates, repeat but keep texts unique.
    while len(questions) < count:
        idx = len(questions) % len(templates)
        base_q, options, answer = templates[idx]
        questions.append({
            "question": f"[{difficulty}] {base_q} (variant {len(questions)+1})",
            "options" : options,
            "answer"  : answer,
        })

    return questions[:count]


def evaluate_quiz_set(
    student_id : str,
    course_id  : str,
    questions  : List[Dict],
    answers    : List[str],
    stream: bool = False,
    token_callback=None,
    max_tokens: int = 250,
) -> Dict:
    """
    Evaluate a full quiz set submission.

    Returns:
        {
            "score"         : float (0-100),
            "correct"       : int,
            "total"         : int,
            "results"       : list of per-question results,
            "weak_topics"   : list of topics student struggled with,
            "feedback"      : str overall feedback,
        }
    """
    def _coerce_question(q: Any) -> Dict[str, Any]:
        if isinstance(q, dict):
            return q
        if hasattr(q, "model_dump"):
            try:
                return q.model_dump()
            except Exception:
                return {}
        if hasattr(q, "dict"):
            try:
                return q.dict()
            except Exception:
                return {}
        return {}

    questions = [_coerce_question(q) for q in questions]

    results     = []
    correct     = 0
    weak_topics = []

    for i, q in enumerate(questions):
        ans = answers[i] if i < len(answers) else ""
        expected = str(q.get("answer", "")).strip().lower()
        given    = (ans or "").strip().lower()

        def _extract_letter(val: str) -> str:
            """
            Extract an answer letter A-D from strings like:
            - "a"
            - "A)"
            - "a) ...option text..."
            """
            s = (val or "").strip()
            if not s:
                return ""
            # Most quiz UI stores just "A"/"B"/"C"/"D"
            m = re.match(r"^([a-dA-D])(?:\s*[\)\.\-].*)?$", s)
            if m:
                return m.group(1).upper()
            # If the user typed an option label like "A) ...", match from the start.
            m2 = re.match(r"^\s*([a-dA-D])\s*[\)\.\-]?", s)
            return m2.group(1).upper() if m2 else ""

        expected_letter = _extract_letter(expected)
        given_letter    = _extract_letter(given)

        # Strict MCQ scoring: only correct if letters match.
        # (Avoid substring matching against full option text which can mark wrong answers correct.)
        is_correct = (
            bool(expected_letter)
            and bool(given_letter)
            and given_letter == expected_letter
        )

        # Fallback for non-MCQ answer types (shouldn't happen for quiz set).
        if not is_correct and not (expected_letter and given_letter):
            is_correct = (given == expected)

        if is_correct:
            correct += 1
        else:
            weak_topics.append("general")

        # Persist each question attempt (best-effort).
        try:
            log_quiz_attempt(
                student_id=student_id.strip().lower(),
                course_id=course_id.strip().lower(),
                topic="general",
                difficulty="unknown",
                question=q.get("question"),
                correct_answer=q.get("answer"),
                student_answer=ans,
                is_correct=bool(is_correct),
                score=1.0 if is_correct else 0.0,
            )
        except Exception:
            pass

        results.append({
            "question"      : q.get("question", ""),
            "your_answer"   : ans,
            "correct_answer": q.get("answer"),
            "is_correct"    : is_correct,
            "explanation"   : "",
            "topic"         : "general",
        })

    score = round((correct / len(questions)) * 100, 1) if questions else 0

    # Generate overall feedback
    try:
        llm    = get_llm(temperature=0.4, max_tokens=max_tokens, streaming=stream)
        prompt = f"""A student scored {score}% ({correct}/{len(questions)}) on a quiz.
Weak topics: {list(set(weak_topics))}.
Write 2 sentences of encouraging, specific feedback and one study tip."""
        if not stream:
            feedback = llm.invoke(prompt).content.strip()
        else:
            from langchain_core.messages import HumanMessage
            tokens = []
            for chunk in llm.stream([HumanMessage(content=prompt)]):
                token = getattr(chunk, "content", None) or getattr(chunk, "text", "")
                if token:
                    tokens.append(token)
                    if token_callback:
                        token_callback(token)
            feedback = "".join(tokens).strip()
    except Exception:
        feedback = f"You scored {score}%. " + (
            "Great work! Keep it up!" if score >= 70 else
            "Keep practising — review the weak topics and try again!"
        )

    return {
        "score"      : score,
        "correct"    : correct,
        "total"      : len(questions),
        "results"    : results,
        "weak_topics": list(set(weak_topics)),
        "feedback"   : feedback,
    }
