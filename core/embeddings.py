"""
Lightweight course material store for Streamlit Cloud.
No FAISS, no sentence-transformers, no system-level build dependencies.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv()

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1600))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 200))
VECTOR_STORE_DIR = Path("data/vector_stores")
COURSES_DIR = Path("data/courses")

VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
COURSES_DIR.mkdir(parents=True, exist_ok=True)


class _Doc:
    def __init__(self, page_content: str, metadata: Optional[Dict] = None):
        self.page_content = page_content
        self.metadata = metadata or {}


def _get_store_path(course_id: str) -> Path:
    """Returns the local JSONL chunk file path for a course."""
    return VECTOR_STORE_DIR / course_id / "chunks.jsonl"


def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: List[str] = []
    start = 0
    step = max(1, chunk_size - max(0, overlap))
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step
    return chunks


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())


class _SimpleRetriever:
    def __init__(self, docs: List[_Doc], top_k: int = 5):
        self.docs = docs
        self.top_k = top_k

    def invoke(self, query: str) -> List[_Doc]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return self.docs[: self.top_k]
        scored = []
        for d in self.docs:
            text = d.page_content.lower()
            score = sum(text.count(tok) for tok in q_tokens)
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            return [d for _, d in scored[: self.top_k]]
        return self.docs[: self.top_k]


def ingest_course_materials(course_id: str, pdf_paths: List[str], extra_text: Optional[str] = None) -> int:
    """
    Ingest PDF files (and optional raw text) into a course-specific local chunk store.

    Args:
        course_id   : Unique identifier for the course (e.g. 'python101')
        pdf_paths   : List of paths to PDF files
        extra_text  : Any additional raw text (e.g. pasted syllabus)

    Returns:
        Total number of chunks stored.
    """
    documents: List[_Doc] = []

    # Load PDFs using pypdf (pure Python wheels on Streamlit Cloud)
    for pdf_path in pdf_paths:
        if not os.path.exists(pdf_path):
            print(f"[WARNING] PDF not found: {pdf_path}, skipping.")
            continue
        try:
            docs = []
            reader = PdfReader(pdf_path)
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    docs.append(
                        _Doc(
                            page_content=text,
                            metadata={
                                "course_id": course_id,
                                "source_type": "pdf",
                                "source": os.path.basename(pdf_path),
                                "page": page_num + 1,
                            },
                        )
                    )
            documents.extend(docs)
            print(f"[INFO] Loaded {len(docs)} pages from {pdf_path}")
        except Exception as e:
            print(f"[ERROR] Failed to load {pdf_path}: {e}")

    # Load extra raw text
    if extra_text:
        documents.append(_Doc(page_content=extra_text, metadata={"course_id": course_id, "source_type": "manual_text"}))

    if not documents:
        raise ValueError(f"No documents loaded for course '{course_id}'")

    # Chunk documents using lightweight text slicing.
    chunks: List[_Doc] = []
    for d in documents:
        parts = _chunk_text(d.page_content, CHUNK_SIZE, CHUNK_OVERLAP)
        for idx, part in enumerate(parts, start=1):
            md = dict(d.metadata)
            md["chunk"] = idx
            chunks.append(_Doc(page_content=part, metadata=md))
    print(f"[INFO] Created {len(chunks)} chunks for course '{course_id}'")

    store_path = _get_store_path(course_id)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with store_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            meta = c.metadata or {}
            safe_line = {
                "page_content": c.page_content,
                "metadata": meta,
            }
            import json
            f.write(json.dumps(safe_line, ensure_ascii=False) + "\n")
    print(f"[INFO] Saved chunks to {store_path}")
    return len(chunks)


def get_retriever(course_id: str, top_k: int = 5):
    """
    Returns a lightweight retriever for a specific course.
    Raises FileNotFoundError if the course has not been ingested yet.

    Usage:
        retriever = get_retriever("python101")
        docs = retriever.invoke("What is a list comprehension?")
    """
    store_path = _get_store_path(course_id)
    if not store_path.exists():
        raise FileNotFoundError(
            f"No vector store found for course '{course_id}'. "
            "Please ingest course materials first."
        )
    docs: List[_Doc] = []
    import json
    with store_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            docs.append(_Doc(item.get("page_content", ""), item.get("metadata") or {}))
    return _SimpleRetriever(docs, top_k=top_k)


def list_courses() -> List[str]:
    """Returns a list of all courses that have been ingested."""
    if not VECTOR_STORE_DIR.exists():
        return []
    result: List[str] = []
    for d in VECTOR_STORE_DIR.iterdir():
        if not d.is_dir():
            continue
        if (d / "chunks.jsonl").exists():
            result.append(d.name)
    return result


def delete_course(course_id: str) -> bool:
    """Deletes the local chunk store for a course."""
    import shutil
    store_path = _get_store_path(course_id)
    if store_path.exists():
        shutil.rmtree(store_path)
        print(f"[INFO] Deleted vector store for '{course_id}'")
        return True
    return False


if __name__ == "__main__":
    courses = list_courses()
    print(f"Available courses: {courses if courses else 'None ingested yet'}")
