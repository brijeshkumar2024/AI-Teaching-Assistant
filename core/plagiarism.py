"""
core/plagiarism.py
──────────────────
AI-detection & plagiarism flagging for student code submissions.
Two-layer check:
  1. Structural fingerprint  — detects copy-paste between students
  2. LLM-based AI-detection  — detects AI-generated code patterns
"""

import os
import re
import hashlib
from typing import Dict, List, Tuple
from difflib import SequenceMatcher
from dotenv import load_dotenv
from core.llm_config import get_llm

load_dotenv()

# ── Thresholds ────────────────────────────────────────────────────────────
SIMILARITY_THRESHOLD   = float(os.getenv("SIMILARITY_THRESHOLD", 0.80))  # 80% match = flag
AI_DETECT_THRESHOLD    = float(os.getenv("AI_DETECT_THRESHOLD",  0.75))  # 75% AI confidence = flag

# ── Submission store: fingerprint → (student_id, code) ────────────────────
_submission_store: Dict[str, Tuple[str, str]] = {}


# ── Helpers ───────────────────────────────────────────────────────────────

def _normalize_code(code: str) -> str:
    """Strip comments, blank lines, and normalize whitespace for comparison."""
    lines = code.splitlines()
    cleaned = []
    for line in lines:
        line = re.sub(r"#.*", "", line)          # remove inline comments
        line = re.sub(r'""".*?"""', "", line, flags=re.DOTALL)
        line = line.strip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


def _fingerprint(code: str) -> str:
    """SHA-256 fingerprint of normalized code."""
    normalized = _normalize_code(code)
    return hashlib.sha256(normalized.encode()).hexdigest()


def _similarity(code_a: str, code_b: str) -> float:
    """SequenceMatcher similarity ratio between two normalized code strings."""
    a = _normalize_code(code_a)
    b = _normalize_code(code_b)
    return SequenceMatcher(None, a, b).ratio()


# ── Main public functions ─────────────────────────────────────────────────

def register_submission(student_id: str, course_id: str, code: str) -> str:
    """
    Register a new code submission.
    Returns the fingerprint hash (use as submission ID).
    """
    fp = _fingerprint(code)
    key = f"{course_id}:{fp}"
    _submission_store[key] = (student_id, code)
    return fp


def check_plagiarism(
    student_id: str,
    course_id: str,
    code: str,
) -> Dict:
    """
    Full plagiarism check: structural similarity + AI-detection.

    Returns:
        {
            "flagged"          : bool,
            "similarity_score" : float,
            "matched_student"  : str | None,
            "ai_generated"     : bool,
            "ai_confidence"    : float,
            "ai_reasoning"     : str,
            "recommendation"   : str,
        }
    """
    result = {
        "flagged"          : False,
        "similarity_score" : 0.0,
        "matched_student"  : None,
        "ai_generated"     : False,
        "ai_confidence"    : 0.0,
        "ai_reasoning"     : "",
        "recommendation"   : "No issues detected.",
    }

    # ── Layer 1: Structural similarity against existing submissions ────────
    for key, (other_student, other_code) in _submission_store.items():
        if not key.startswith(f"{course_id}:"):
            continue
        if other_student == student_id:
            continue
        score = _similarity(code, other_code)
        if score > result["similarity_score"]:
            result["similarity_score"] = round(score, 3)
            if score >= SIMILARITY_THRESHOLD:
                result["flagged"]         = True
                result["matched_student"] = other_student
                result["recommendation"]  = (
                    f"High similarity ({score:.0%}) with {other_student}'s submission. "
                    "Instructor review required."
                )

    # ── Layer 2: LLM-based AI-generation detection ────────────────────────
    ai_result = _detect_ai_generated(code)
    result["ai_generated"]  = ai_result["is_ai"]
    result["ai_confidence"] = ai_result["confidence"]
    result["ai_reasoning"]  = ai_result["reasoning"]

    if ai_result["is_ai"] and ai_result["confidence"] >= AI_DETECT_THRESHOLD:
        result["flagged"] = True
        result["recommendation"] = (
            f"Code shows AI-generation patterns (confidence: {ai_result['confidence']:.0%}). "
            f"Reason: {ai_result['reasoning']} Instructor review recommended."
        )

    return result


def _detect_ai_generated(code: str) -> Dict:
    """
    Uses the LLM to assess whether code appears AI-generated.
    Returns confidence score and reasoning.
    """
    llm = get_llm(temperature=0.0)

    prompt = f"""You are an expert code reviewer tasked with detecting AI-generated code.

Analyze the following Python code and determine if it was likely written by an AI (e.g., ChatGPT, Copilot, Gemini) or by a human student.

Signs of AI-generated code:
- Overly consistent and perfect formatting
- Unusual completeness for a beginner assignment
- Generic, textbook-style variable names (e.g., num1, num2, result)
- Perfectly structured docstrings on simple functions
- No beginner mistakes, typos, or exploratory comments
- Unnaturally polished for the assignment difficulty level

Code to analyze:
```python
{code}
```

Respond ONLY in this exact format:
IS_AI: true/false
CONFIDENCE: 0.0 to 1.0
REASONING: One sentence explaining your assessment.
"""

    try:
        response = llm.invoke(prompt)
        text = response.content.strip()

        is_ai      = "true" in text.lower().split("is_ai:")[-1].split("\n")[0].lower()
        confidence = float(re.search(r"CONFIDENCE:\s*([\d.]+)", text).group(1))
        reasoning  = re.search(r"REASONING:\s*(.+)", text).group(1).strip()

        return {"is_ai": is_ai, "confidence": confidence, "reasoning": reasoning}

    except Exception as e:
        return {"is_ai": False, "confidence": 0.0, "reasoning": f"Detection error: {str(e)}"}


def get_course_submission_stats(course_id: str) -> Dict:
    """Returns submission count and flagged count for a course."""
    total   = sum(1 for k in _submission_store if k.startswith(f"{course_id}:"))
    return {"course_id": course_id, "total_submissions": total}


if __name__ == "__main__":
    sample_code = '''
def add_numbers(num1, num2):
    """Add two numbers and return the result."""
    result = num1 + num2
    return result

if __name__ == "__main__":
    print(add_numbers(5, 3))
'''
    register_submission("alice", "python101", sample_code)
    report = check_plagiarism("bob", "python101", sample_code)
    print(report)