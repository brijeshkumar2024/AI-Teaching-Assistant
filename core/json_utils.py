"""
core/json_utils.py
-------------------
Helpers for safely handling and validating JSON returned by LLMs.

Key goals:
- Strip markdown fences
- Validate against a strict quiz schema
- Never pass raw LLM text directly into Pydantic before json.loads succeeds
"""

import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


def _strip_fences(text: str) -> str:
    """Remove ```json fences or trailing backticks the model might add."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


class QuizQuestion(BaseModel):
    """Minimal quiz question schema expected by the UI."""

    model_config = ConfigDict(extra="ignore", frozen=False)

    question: str
    options: List[str]
    answer: str
    difficulty: Optional[str] = None  # kept for internal filtering; stripped for UI

    @field_validator("question")
    @classmethod
    def _non_empty_question(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("question cannot be empty")
        return v

    @field_validator("options")
    @classmethod
    def _options_list(cls, v: Any) -> List[str]:
        if not isinstance(v, list):
            raise ValueError("options must be a list")
        cleaned = [str(o).strip() for o in v if str(o).strip()]
        if not cleaned:
            raise ValueError("options list cannot be empty")
        # Limit to first 4 to keep UI compact
        return cleaned[:4]

    @field_validator("answer")
    @classmethod
    def _normalize_answer(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("answer cannot be empty")
        # Normalise MCQ answers like "A)" -> "A"
        if len(v) >= 2 and v[1] in [")", "."]:
            v = v[0]
        return v

    @field_validator("difficulty")
    @classmethod
    def _lower_difficulty(cls, v: Optional[str]) -> Optional[str]:
        return v.lower().strip() if isinstance(v, str) and v.strip() else None


class QuizPayload(BaseModel):
    """Top-level quiz payload with a list of questions."""

    model_config = ConfigDict(extra="allow")

    questions: List[QuizQuestion]

    @field_validator("questions")
    @classmethod
    def _at_least_one(cls, v: List[QuizQuestion]) -> List[QuizQuestion]:
        if not v:
            raise ValueError("no questions provided")
        return v


def parse_quiz_json(raw_text: str, expected_count: Optional[int] = None) -> Dict[str, Any]:
    """
    Parse and validate LLM output into the strict quiz schema.

    Returns a dict containing only JSON-serialisable primitives:
    {
        "questions": [
            {"question": "...", "options": [...], "answer": "...", "difficulty": "easy"|None}
        ]
    }
    """
    cleaned = _strip_fences(raw_text)
    try:
        data = json.loads(cleaned)
        payload = QuizPayload.model_validate(data)
        # Ensure dict for UI - strip Pydantic
        payload_dict = payload.model_dump()
    except (json.JSONDecodeError, ValidationError):
        # Fallback for malformed LLM output
        return {"questions": []}

    questions = payload_dict.get('questions', [])
    if expected_count:
        questions = questions[:expected_count]

    sanitized = []
    for q in questions:
        item = {
            "question": q.get('question', ''),
            "options": q.get('options', []),
            "answer": q.get('answer', ''),
        }
        diff = q.get('difficulty')
        if diff:
            item["difficulty"] = diff
        sanitized.append(item)

    return {"questions": sanitized}


def safe_json(text: str) -> Any:
    """
    Convenience wrapper that strips fences and parses JSON.
    """
    return json.loads(_strip_fences(text))
