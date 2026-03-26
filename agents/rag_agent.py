"""
agents/rag_agent.py
───────────────────
RAG-powered Q&A agent.
Retrieves relevant chunks from the course FAISS index,
builds a pedagogical prompt, and returns a context-aware answer.
Supports multi-turn memory and topic detection.
"""

import re
import time
from typing import Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from core.llm_config import get_llm
from core.embeddings import get_retriever
from database.models import log_interaction
try:
    from core.persistent_memory import get_history_as_text, save_interaction
except Exception:
    from core.memory import get_history_as_text, save_interaction


# ── Pedagogical system prompt ──────────────────────────────────────────────
SYSTEM_PROMPT = """You are an AI Teaching Assistant for a programming course.
Goal: explain concepts clearly and encourage learning (HINTS only; don't write full solutions).

Use the provided `Course context` as the primary source. If it doesn't cover the topic, say so.
Keep your answer concise (150–260 words), structured, and beginner-friendly.

Course context:
{context}

Conversation history:
{chat_history}
"""

RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{question}"),
])


# ── Topic detection ────────────────────────────────────────────────────────
TOPIC_KEYWORDS = {
    "loops"       : ["for", "while", "loop", "iterate", "iteration"],
    "functions"   : ["def", "function", "return", "parameter", "argument"],
    "recursion"   : ["recursion", "recursive", "base case", "call itself"],
    "oop"         : ["class", "object", "inheritance", "method", "instance"],
    "data_structures": ["list", "dict", "tuple", "set", "array", "stack", "queue"],
    "algorithms"  : ["sort", "search", "binary", "complexity", "big o"],
    "exceptions"  : ["try", "except", "error", "exception", "raise"],
    "files"       : ["file", "open", "read", "write", "csv", "json"],
}


def detect_topics(text: str) -> List[str]:
    """Detect programming topics mentioned in a student's message."""
    text_lower = text.lower()
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(topic)
    return found


def _format_docs(docs) -> str:
    """Formats retrieved documents into a readable context string."""
    if not docs:
        return "No relevant course material found."
    sections = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "Course material")
        page   = doc.metadata.get("page", "")
        label  = f"[{i}] {source}" + (f" (p.{page})" if page else "")
        # Keep context compact to reduce prompt size + latency.
        content = (doc.page_content or "").strip()
        sections.append(f"{label}\n{content[:1200]}")
    return "\n\n---\n\n".join(sections)


# ── Main agent function ────────────────────────────────────────────────────

def run_rag_agent(
    student_id: str,
    course_id: str,
    question: str,
    top_k: int = 5,
    stream: bool = False,
    token_callback=None,
    max_tokens: int = 900,
    max_retries: int = 3,
) -> Dict:
    """
    Run the RAG Q&A agent for a student question.

    Args:
        student_id : Unique student identifier
        course_id  : Course to retrieve context from
        question   : The student's question
        top_k      : Number of chunks to retrieve

    Returns:
        {
            "answer"         : str,
            "sources"        : list,
            "topics"         : list,
            "response_time"  : float,
            "context_found"  : bool,
        }
    """
    start_time = time.time()

    # ── Retrieve context ──────────────────────────────────────────────────
    try:
        retriever = get_retriever(course_id, top_k=top_k)
        docs      = retriever.invoke(question)
        context   = _format_docs(docs)
        context_found = bool(docs)
    except (FileNotFoundError, RuntimeError, Exception) as e:
        err_msg = str(e)
        if "No such file" in err_msg or "could not open" in err_msg or "FileNotFoundError" in err_msg:
            context = (
                f"No course materials have been ingested for '{course_id}' yet. "
                "Please upload PDF lecture notes using the Upload Course Materials panel in the sidebar."
            )
        else:
            context = f"Could not retrieve course materials: {err_msg[:100]}"
        docs          = []
        context_found = False

    # ── Build prompt with memory ──────────────────────────────────────────
    chat_history = get_history_as_text(student_id, course_id)

    # ── Call LLM ─────────────────────────────────────────────────────────
    llm = get_llm(temperature=0.3, max_tokens=max_tokens, streaming=stream)
    chain = RAG_PROMPT | llm | StrOutputParser()

    inputs = {
        "context"      : context,
        "chat_history" : chat_history,
        "question"     : question,
    }

    if not stream:
        answer = chain.invoke(inputs)
        answer_text = answer.strip()
    else:
        tokens = []
        for attempt in range(max_retries):
            try:
                tokens = []
                for chunk in chain.stream(inputs):
                    # With StrOutputParser, `chunk` is expected to be a string.
                    token = chunk if isinstance(chunk, str) else getattr(chunk, "content", "")
                    if token:
                        tokens.append(token)
                        if token_callback:
                            token_callback(token)
                answer_text = "".join(tokens).strip()
                break
            except Exception as e:  # noqa: BLE001
                err = str(e)
                if attempt < max_retries - 1 and any(x in err for x in ["429", "RESOURCE_EXHAUSTED", "quota", "rate_limit"]):
                    time.sleep([10, 30, 60][attempt])
                    continue
                raise

    # ── Save to memory ────────────────────────────────────────────────────
    save_interaction(student_id, course_id, question, answer_text)

    # ── Detect topics ─────────────────────────────────────────────────────
    topics = detect_topics(question + " " + answer_text)

    elapsed = round((time.time() - start_time) * 1000)

    # ── Persist analytics event to MongoDB ───────────────────────────────
    try:
        log_interaction(
            student_id=student_id.strip().lower(),
            course_id=course_id.strip().lower(),
            interaction_type="qa",
            student_message=question,
            ai_response=answer_text,
            topics=topics,
            response_time_ms=elapsed,
        )
    except Exception:
        # Dashboard must never crash due to analytics logging failures.
        pass

    # ── Extract source names ──────────────────────────────────────────────
    sources = list({
        doc.metadata.get("source", "Course material") for doc in docs
    })

    return {
        "answer"        : answer_text,
        "sources"       : sources,
        "topics"        : topics,
        "response_time" : elapsed,
        "context_found" : context_found,
    }


if __name__ == "__main__":
    result = run_rag_agent(
        student_id = "test_student",
        course_id  = "python101",
        question   = "What is a list comprehension and when should I use it?",
    )
    print(f"Answer:\n{result['answer']}")
    print(f"\nTopics detected: {result['topics']}")
    print(f"Response time  : {result['response_time']}ms")