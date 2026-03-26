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

from core.llm_config import get_llm, call_llm_with_retry
from core.embeddings import get_retriever
try:
    from core.persistent_memory import get_history_as_text, save_interaction
except Exception:
    from core.memory import get_history_as_text, save_interaction


# ── Pedagogical system prompt ──────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert AI Teaching Assistant for a programming course.
Your role is to help students understand concepts — NOT to do their work for them.

Guidelines:
- Use the retrieved course context as your primary knowledge source
- Give clear, step-by-step explanations tailored to a beginner-to-intermediate level
- Use analogies and real-world examples to make concepts stick
- Ask a clarifying follow-up question if the student seems confused
- Never write complete solutions to assignments — give hints and guide thinking instead
- If the context doesn't cover the topic, say so honestly and give a general explanation
- Keep responses concise but complete (150–300 words ideal)
- Always be encouraging and supportive

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
        sections.append(f"{label}\n{doc.page_content.strip()}")
    return "\n\n---\n\n".join(sections)


# ── Main agent function ────────────────────────────────────────────────────

def run_rag_agent(
    student_id: str,
    course_id: str,
    question: str,
    top_k: int = 5,
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
    except FileNotFoundError:
        context       = "No course materials have been ingested for this course yet."
        docs          = []
        context_found = False

    # ── Build prompt with memory ──────────────────────────────────────────
    chat_history = get_history_as_text(student_id, course_id)

    # ── Call LLM ─────────────────────────────────────────────────────────
    llm    = get_llm()
    chain  = RAG_PROMPT | llm | StrOutputParser()

    answer = chain.invoke({
        "context"      : context,
        "chat_history" : chat_history,
        "question"     : question,
    })

    # ── Save to memory ────────────────────────────────────────────────────
    save_interaction(student_id, course_id, question, answer)

    # ── Detect topics ─────────────────────────────────────────────────────
    topics = detect_topics(question + " " + answer)

    elapsed = round((time.time() - start_time) * 1000)

    # ── Extract source names ──────────────────────────────────────────────
    sources = list({
        doc.metadata.get("source", "Course material") for doc in docs
    })

    return {
        "answer"        : answer,
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