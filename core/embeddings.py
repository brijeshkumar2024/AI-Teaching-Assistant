"""
core/embeddings.py
──────────────────
Multi-course FAISS vector store manager.
Each course gets its own isolated knowledge base.
Supports PDF ingestion, chunking, embedding, and retrieval.
"""

import os
import pickle
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
import fitz  # pymupdf direct
try:
    from langchain_community.vectorstores import FAISS
except ImportError:
    from langchain.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHUNK_SIZE       = int(os.getenv("CHUNK_SIZE", 2048))
CHUNK_OVERLAP    = int(os.getenv("CHUNK_OVERLAP", 256))
VECTOR_STORE_DIR = Path("data/vector_stores")
COURSES_DIR      = Path("data/courses")

VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
COURSES_DIR.mkdir(parents=True, exist_ok=True)

_EMBEDDINGS_MODEL = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    """Load the sentence-transformer embedding model (cached after first load)."""
    global _EMBEDDINGS_MODEL
    if _EMBEDDINGS_MODEL is not None:
        return _EMBEDDINGS_MODEL
    _EMBEDDINGS_MODEL = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    return _EMBEDDINGS_MODEL


def _get_store_path(course_id: str) -> Path:
    """Returns the FAISS index directory for a given course."""
    return VECTOR_STORE_DIR / course_id


def ingest_course_materials(
    course_id: str,
    pdf_paths: List[str],
    extra_text: Optional[str] = None,
) -> int:
    """
    Ingest PDF files (and optional raw text) into a course-specific FAISS index.

    Args:
        course_id   : Unique identifier for the course (e.g. 'python101')
        pdf_paths   : List of paths to PDF files
        extra_text  : Any additional raw text (e.g. pasted syllabus)

    Returns:
        Total number of chunks stored.
    """
    documents: List[Document] = []

    # Load PDFs using pymupdf directly
    for pdf_path in pdf_paths:
        if not os.path.exists(pdf_path):
            print(f"[WARNING] PDF not found: {pdf_path}, skipping.")
            continue
        try:
            pdf_doc = fitz.open(pdf_path)
            docs = []
            for page_num in range(len(pdf_doc)):
                page = pdf_doc[page_num]
                text = page.get_text()
                if text.strip():
                    docs.append(Document(
                        page_content=text,
                        metadata={
                            "course_id"  : course_id,
                            "source_type": "pdf",
                            "source"     : os.path.basename(pdf_path),
                            "page"       : page_num + 1,
                        }
                    ))
            pdf_doc.close()
            documents.extend(docs)
            print(f"[INFO] Loaded {len(docs)} pages from {pdf_path}")
        except Exception as e:
            print(f"[ERROR] Failed to load {pdf_path}: {e}")

    # Load extra raw text
    if extra_text:
        documents.append(Document(
            page_content=extra_text,
            metadata={"course_id": course_id, "source_type": "manual_text"}
        ))

    if not documents:
        raise ValueError(f"No documents loaded for course '{course_id}'")

    # Chunk documents
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    print(f"[INFO] Created {len(chunks)} chunks for course '{course_id}'")

    # Build or update FAISS index
    embeddings = _get_embeddings()
    store_path = _get_store_path(course_id)

    if store_path.exists():
        # Merge with existing index
        vector_store = FAISS.load_local(
            str(store_path),
            embeddings,
            allow_dangerous_deserialization=True
        )
        vector_store.add_documents(chunks)
        print(f"[INFO] Merged into existing index for '{course_id}'")
    else:
        vector_store = FAISS.from_documents(chunks, embeddings)
        print(f"[INFO] Created new index for '{course_id}'")

    vector_store.save_local(str(store_path))
    print(f"[INFO] Saved index to {store_path}")
    return len(chunks)


def get_retriever(course_id: str, top_k: int = 5):
    """
    Returns a LangChain retriever for a specific course.
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
    embeddings = _get_embeddings()
    vector_store = FAISS.load_local(
        str(store_path),
        embeddings,
        allow_dangerous_deserialization=True
    )
    return vector_store.as_retriever(
        search_type="mmr",               # Max Marginal Relevance for diversity
        search_kwargs={"k": top_k, "fetch_k": top_k * 3},
    )


def list_courses() -> List[str]:
    """Returns a list of all courses that have been ingested."""
    if not VECTOR_STORE_DIR.exists():
        return []
    return [d.name for d in VECTOR_STORE_DIR.iterdir() if d.is_dir()]


def delete_course(course_id: str) -> bool:
    """Deletes the FAISS index for a course."""
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
