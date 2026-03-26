"""
agents/orchestrator.py
───────────────────────
LangGraph-powered orchestrator — compatible with langgraph 0.2.x and 0.3.x+
Classifies every student message and routes it to the correct agent.
"""

import re
import time
import traceback
from typing import Dict, List, Literal, Optional, TypedDict, Annotated, Tuple
from threading import Thread
from queue import Queue

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# ── LangGraph imports with version compatibility ──────────────────────────
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    print("[WARNING] langgraph not available — using simple router fallback")

from core.llm_config import get_llm
from agents.rag_agent         import run_rag_agent
from agents.code_review_agent import run_code_review_agent
from agents.quiz_agent        import generate_question, evaluate_answer
from agents.analytics_agent   import log_event
from database.models import log_code_submission


# ─────────────────────────────────────────────────────────────────────────────
# State schema
# ─────────────────────────────────────────────────────────────────────────────

class TAState(TypedDict):
    messages       : List[BaseMessage]
    student_id     : str
    course_id      : str
    intent         : Optional[str]
    agent_used     : Optional[str]
    student_input  : Optional[str]
    code_block     : Optional[str]
    topic          : Optional[str]
    quiz_question  : Optional[Dict]
    pending_answer : Optional[str]
    response       : Optional[str]
    metadata       : Optional[Dict]


# ─────────────────────────────────────────────────────────────────────────────
# Intent classification
# ─────────────────────────────────────────────────────────────────────────────

INTENT_PROMPT = """You are a classifier for an AI Teaching Assistant.
Classify the student message into exactly ONE of these intents:
- code_submission  : message contains a code block or indented code to be reviewed
- quiz_request     : student wants to practice, take a quiz, or test their knowledge
- quiz_answer      : student is answering an active quiz question
- conceptual_qa    : question about a programming concept or course material
- smalltalk        : greeting, thanks, or off-topic

Return ONLY one word from the list above. Nothing else.

Student message: {message}
Has active quiz question: {has_quiz}
"""


def classify_intent(state: TAState) -> TAState:
    message  = state["student_input"] or ""
    has_quiz = state.get("quiz_question") is not None

    # Fast path: detect code blocks
    if "```" in message or re.search(r"\n( {4}|\t).+", message):
        state["intent"] = "code_submission"
        return state

    # Fast path: active quiz + short reply = answer
    if has_quiz and len(message.strip().split()) <= 10:
        state["intent"] = "quiz_answer"
        return state

    # Fast path: keyword detection
    msg_lower = message.lower()

    # Quiz detection — highest priority after code
    if any(w in msg_lower for w in ["quiz", "test me", "practice", "question me"]):
        state["intent"] = "quiz_request"
        return state

    # Personal questions always go to smalltalk
    personal_triggers = ["my name", "what am i", "who am i", "introduce", "about me"]
    if any(t in msg_lower for t in personal_triggers):
        state["intent"] = "smalltalk"
        return state

    # Smalltalk — ONLY pure greetings, nothing with question words
    smalltalk_only = ["hi", "hello", "hey", "thanks", "thank you", "bye", "good morning", "good night"]
    qa_indicators  = ["what", "how", "why", "when", "which", "who", "where", "explain",
                      "define", "tell me", "describe", "difference", "example", "does",
                      "is ", "are ", "can ", "should", "could", "would", "dataset",
                      "pdf", "lecture", "topic", "about", "content", "chapter", "meeting"]
    has_qa  = any(w in msg_lower for w in qa_indicators)
    is_pure_smalltalk = any(msg_lower.strip().startswith(w) for w in smalltalk_only) and not has_qa

    if is_pure_smalltalk:
        state["intent"] = "smalltalk"
        return state

    # Any question word or course-related term → RAG Q&A
    if has_qa:
        state["intent"] = "conceptual_qa"
        return state

    # Default to conceptual_qa — no LLM call needed for classification
    # This saves 1 full API call per message = 2x speed improvement
    state["intent"] = "conceptual_qa"
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Agent handlers (pure functions — work with or without LangGraph)
# ─────────────────────────────────────────────────────────────────────────────

def handle_qa(state: TAState) -> TAState:
    result = run_rag_agent(
        student_id=state["student_id"],
        course_id =state["course_id"],
        question  =state["student_input"],
    )
    log_event(state["course_id"], state["student_id"], "qa",
              ", ".join(result["topics"]) or "general", success=True)
    state["response"]   = result["answer"]
    state["agent_used"] = "rag_qa"
    state["topic"]      = ", ".join(result["topics"])
    state["metadata"]   = {
        "sources"      : result["sources"],
        "context_found": result["context_found"],
        "response_time": result["response_time"],
    }
    state["messages"].append(AIMessage(content=result["answer"]))
    return state


def handle_code(state: TAState) -> TAState:
    raw   = state["student_input"] or ""
    match = re.search(r"```(?:python)?\s*\n?([\s\S]+?)```", raw)
    code  = match.group(1).strip() if match else raw.strip()
    topic = re.sub(r"```[\s\S]*?```", "", raw).strip()[:100] or "General Python"

    result = run_code_review_agent(
        student_id=state["student_id"],
        course_id =state["course_id"],
        code      =code,
        topic     =topic,
    )
    log_event(state["course_id"], state["student_id"], "code_review",
              topic, success=(result["execution"]["exit_code"] == 0))

    # Persist code review analytics to MongoDB (best-effort).
    try:
        exec_info = result.get("execution", {})
        log_code_submission(
            student_id=state["student_id"].strip().lower(),
            course_id=state["course_id"].strip().lower(),
            code=code,
            execution_output=(exec_info.get("stdout") or "") + (("\n" + exec_info.get("stderr")) if exec_info.get("stderr") else ""),
            execution_passed=(exec_info.get("exit_code") == 0),
            ai_feedback=result.get("feedback"),
            plagiarism_score=float(result.get("plagiarism", {}).get("similarity_score", 0.0) or 0.0),
            ai_generated_flag=bool(result.get("plagiarism", {}).get("ai_generated", False)),
        )
    except Exception:
        print(traceback.format_exc())

    response = result["feedback"]
    exec_info = result["execution"]
    if exec_info["exit_code"] == 0 and exec_info["stdout"]:
        response += f"\n\n**Output:**\n```\n{exec_info['stdout'].strip()}\n```"
    elif exec_info["stderr"]:
        response += f"\n\n**Error:**\n```\n{exec_info['stderr'].strip()[:300]}\n```"
    if result["plagiarism"]["flagged"]:
        response += f"\n\n⚠️ **Academic Integrity Notice:** {result['plagiarism']['recommendation']}"

    state["response"]   = response
    state["agent_used"] = "code_review"
    state["code_block"] = code
    state["metadata"]   = {
        "tests_passed"  : result["tests_passed"],
        "tests_total"   : result["tests_total"],
        "execution_mode": exec_info.get("execution_mode"),
        "plagiarism"    : result["plagiarism"],
    }
    state["messages"].append(AIMessage(content=response))
    return state


def handle_quiz_generate(state: TAState) -> TAState:
    msg = state["student_input"].lower()
    topic_map = {
        "loop": "loops", "for": "loops", "while": "loops",
        "function": "functions", "recursion": "recursion",
        "class": "oop", "object": "oop",
        "list": "data_structures", "dict": "data_structures",
        "sort": "algorithms", "exception": "exceptions",
        "error": "exceptions", "file": "files",
    }
    topic = next((v for k, v in topic_map.items() if k in msg), "general_python")
    fmt   = "true_false" if "true" in msg or "false" in msg else \
            "short_answer" if "short" in msg else "mcq"

    question = generate_question(
        student_id=state["student_id"],
        course_id =state["course_id"],
        topic     =topic,
        fmt       =fmt,
    )

    response  = f"**Quiz — {topic.replace('_',' ').title()} ({question['difficulty'].upper()})**\n\n"
    response += f"**Q:** {question['question']}\n\n"
    if question["options"]:
        response += "\n".join(question["options"]) + "\n\n"
    response += f"*Hint: {question['hint']}*\n\n"
    response += "_Type your answer below (e.g. A, B, True, or a short phrase)_"

    log_event(state["course_id"], state["student_id"], "quiz", topic, success=True)
    state["response"]      = response
    state["agent_used"]    = "quiz_generate"
    state["quiz_question"] = question
    state["topic"]         = topic
    state["metadata"]      = {"difficulty": question["difficulty"], "format": fmt}
    state["messages"].append(AIMessage(content=response))
    return state


def handle_quiz_evaluate(state: TAState) -> TAState:
    quiz_question  = state.get("quiz_question")
    student_answer = state["student_input"]

    if not quiz_question:
        state["response"]   = "I don't have an active quiz question. Type 'quiz me on loops' to start one!"
        state["agent_used"] = "quiz_evaluate"
        state["messages"].append(AIMessage(content=state["response"]))
        return state

    result = evaluate_answer(
        student_id    =state["student_id"],
        course_id     =state["course_id"],
        question_data =quiz_question,
        student_answer=student_answer,
    )
    log_event(state["course_id"], state["student_id"], "quiz",
              quiz_question.get("topic", "general"), success=result["is_correct"])

    icon     = "✅" if result["is_correct"] else "❌"
    response  = f"{icon} **{'Correct!' if result['is_correct'] else 'Not quite!'}**\n\n"
    response += f"{result['feedback']}\n\n"
    response += f"**Key takeaway:** {result['teaching_point']}\n\n"
    response += f"_Next difficulty: **{result['new_difficulty']}**_ — type 'quiz me' to continue!"

    state["quiz_question"] = None
    state["response"]      = response
    state["agent_used"]    = "quiz_evaluate"
    state["metadata"]      = {
        "is_correct"    : result["is_correct"],
        "score"         : result["score"],
        "new_difficulty": result["new_difficulty"],
    }
    state["messages"].append(AIMessage(content=response))
    return state


def handle_smalltalk(state: TAState) -> TAState:
    try:
        llm    = get_llm(temperature=0.7)
        prompt = (
            f'You are a warm, encouraging AI Teaching Assistant for a programming course. '
            f'The student\'s name is {state["student_id"].replace("_", " ").title()}. '
            f'The student said: "{state["student_input"]}". '
            f'If they ask their name, tell them their name is {state["student_id"].replace("_", " ").title()}. '
            f'Respond briefly (2-3 sentences). Be friendly and personal. '
            f'Gently redirect to learning if off-topic.'
        )
        response = llm.invoke(prompt)
        state["response"] = response.content.strip()
    except Exception as e:
        state["response"] = f"Hey {state['student_id'].replace('_', ' ').title()}! 👋 I'm here to help you learn. Ask me anything about your course!"

    state["agent_used"] = "smalltalk"
    state["messages"].append(AIMessage(content=state["response"]))
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Router — works with or without LangGraph
# ─────────────────────────────────────────────────────────────────────────────

HANDLER_MAP = {
    "conceptual_qa"  : handle_qa,
    "code_submission": handle_code,
    "quiz_request"   : handle_quiz_generate,
    "quiz_answer"    : handle_quiz_evaluate,
    "smalltalk"      : handle_smalltalk,
}


def _build_langgraph():
    """Build compiled LangGraph (used if langgraph is available)."""
    graph = StateGraph(TAState)
    graph.add_node("classify",             classify_intent)
    graph.add_node("handle_qa",            handle_qa)
    graph.add_node("handle_code",          handle_code)
    graph.add_node("handle_quiz_generate", handle_quiz_generate)
    graph.add_node("handle_quiz_evaluate", handle_quiz_evaluate)
    graph.add_node("handle_smalltalk",     handle_smalltalk)

    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", lambda s: {
        "conceptual_qa"  : "handle_qa",
        "code_submission": "handle_code",
        "quiz_request"   : "handle_quiz_generate",
        "quiz_answer"    : "handle_quiz_evaluate",
        "smalltalk"      : "handle_smalltalk",
    }.get(s.get("intent", "conceptual_qa"), "handle_qa"), {
        "handle_qa"            : "handle_qa",
        "handle_code"          : "handle_code",
        "handle_quiz_generate" : "handle_quiz_generate",
        "handle_quiz_evaluate" : "handle_quiz_evaluate",
        "handle_smalltalk"     : "handle_smalltalk",
    })
    for node in ["handle_qa", "handle_code", "handle_quiz_generate",
                 "handle_quiz_evaluate", "handle_smalltalk"]:
        graph.add_edge(node, END)

    return graph.compile()


# Build graph once at import time
_graph = _build_langgraph() if LANGGRAPH_AVAILABLE else None


# ─────────────────────────────────────────────────────────────────────────────
# Session store + public chat() function
# ─────────────────────────────────────────────────────────────────────────────

_sessions: Dict[str, TAState] = {}


def get_or_create_session(student_id: str, course_id: str) -> TAState:
    key = f"{student_id}:{course_id}"
    if key not in _sessions:
        _sessions[key] = TAState(
            messages      =[],
            student_id    =student_id,
            course_id     =course_id,
            intent        =None,
            agent_used    =None,
            student_input =None,
            code_block    =None,
            topic         =None,
            quiz_question =None,
            pending_answer=None,
            response      =None,
            metadata      ={},
        )
    return _sessions[key]


def chat(student_id: str, course_id: str, message: str) -> Dict:
    """
    Main entry point for all student interactions.
    Uses LangGraph if available, falls back to simple router otherwise.
    """
    start   = time.time()
    session = get_or_create_session(student_id, course_id)
    session["student_input"] = message
    session["messages"].append(HumanMessage(content=message))

    if _graph is not None:
        # LangGraph path
        result = _graph.invoke(session)
    else:
        # Simple fallback router
        result = classify_intent(session)
        handler = HANDLER_MAP.get(result.get("intent", "conceptual_qa"), handle_qa)
        result  = handler(result)

    # Persist session
    key = f"{student_id}:{course_id}"
    _sessions[key] = result

    elapsed = round((time.time() - start) * 1000)
    return {
        "response"  : result.get("response", "Sorry, I could not process that. Please try again."),
        "agent_used": result.get("agent_used", "unknown"),
        "intent"    : result.get("intent",     "unknown"),
        "metadata"  : result.get("metadata",   {}),
        "elapsed_ms": elapsed,
    }


def chat_stream(student_id: str, course_id: str, message: str) -> Tuple:
    """
    Streaming chat entry point for Streamlit.

    Returns:
      (token_generator, result_container)

    token_generator yields incremental text chunks for `st.write_stream(...)`.
    result_container is a dict that will contain the final response payload.
    """
    q: Queue = Queue()
    DONE = object()
    result_container: Dict[str, Optional[Dict]] = {"result": None, "error": None}

    def on_token(tok: str) -> None:
        if tok:
            q.put(tok)

    def worker() -> None:
        start = time.time()
        try:
            session = get_or_create_session(student_id, course_id)
            session["student_input"] = message
            session["messages"].append(HumanMessage(content=message))

            session = classify_intent(session)
            intent = session.get("intent", "conceptual_qa")

            if intent == "conceptual_qa":
                result = run_rag_agent(
                    student_id=student_id,
                    course_id=course_id,
                    question=message,
                    stream=True,
                    token_callback=on_token,
                )
                log_event(course_id, student_id, "qa", ", ".join(result["topics"]) or "general", success=True)
                session["response"] = result["answer"]
                session["agent_used"] = "rag_qa"
                session["topic"] = ", ".join(result["topics"])
                session["metadata"] = {
                    "sources": result["sources"],
                    "context_found": result["context_found"],
                    "response_time": result["response_time"],
                }
                session["messages"].append(AIMessage(content=result["answer"]))

            elif intent == "code_submission":
                raw = message or ""
                match = re.search(r"```(?:python)?\s*\n?([\s\S]+?)```", raw)
                code = match.group(1).strip() if match else raw.strip()
                topic = re.sub(r"```[\s\S]*?```", "", raw).strip()[:100] or "General Python"

                result_code = run_code_review_agent(
                    student_id=student_id,
                    course_id=course_id,
                    code=code,
                    topic=topic,
                    stream=True,
                    token_callback=on_token,
                )
                log_event(course_id, student_id, "code_review", topic, success=(result_code["execution"]["exit_code"] == 0))

                # Persist code submission analytics to MongoDB.
                try:
                    exec_info = result_code.get("execution", {})
                    log_code_submission(
                        student_id=student_id.strip().lower(),
                        course_id=course_id.strip().lower(),
                        code=code,
                        execution_output=(exec_info.get("stdout") or "") + (
                            (("\n" + exec_info.get("stderr")) if exec_info.get("stderr") else "")
                        ),
                        execution_passed=(exec_info.get("exit_code") == 0),
                        ai_feedback=result_code.get("feedback"),
                        plagiarism_score=float(result_code.get("plagiarism", {}).get("similarity_score", 0.0) or 0.0),
                        ai_generated_flag=bool(result_code.get("plagiarism", {}).get("ai_generated", False)),
                    )
                except Exception:
                    print(traceback.format_exc())

                response = result_code["feedback"]
                exec_info = result_code["execution"]
                if exec_info["exit_code"] == 0 and exec_info["stdout"]:
                    response += f"\n\n**Output:**\n```\n{exec_info['stdout'].strip()}\n```"
                elif exec_info["stderr"]:
                    response += f"\n\n**Error:**\n```\n{exec_info['stderr'].strip()[:300]}\n```"
                if result_code["plagiarism"]["flagged"]:
                    response += f"\n\n⚠️ **Academic Integrity Notice:** {result_code['plagiarism']['recommendation']}"

                session["response"] = response
                session["agent_used"] = "code_review"
                session["code_block"] = code
                session["metadata"] = {
                    "tests_passed": result_code["tests_passed"],
                    "tests_total": result_code["tests_total"],
                    "execution_mode": exec_info.get("execution_mode"),
                    "plagiarism": result_code["plagiarism"],
                }
                session["messages"].append(AIMessage(content=response))

            elif intent == "smalltalk":
                # Stream only the assistant response (not any JSON parsing).
                prompt = (
                    "You are a warm and encouraging programming-course assistant.\n"
                    f"Student name: {student_id.replace('_',' ').title()}.\n"
                    f"Student message: {message}.\n"
                    "Reply in 2-3 sentences. If off-topic, gently redirect to learning."
                )
                llm = get_llm(temperature=0.7, max_tokens=300, streaming=True)
                tokens: List[str] = []
                for chunk in llm.stream([HumanMessage(content=prompt)]):
                    token = getattr(chunk, "content", None) or getattr(chunk, "text", "")
                    if token:
                        tokens.append(token)
                        on_token(token)
                session["response"] = "".join(tokens).strip()
                session["agent_used"] = "smalltalk"
                session["messages"].append(AIMessage(content=session["response"]))

            elif intent == "quiz_request":
                session = handle_quiz_generate(session)
                resp = session.get("response", "")
                
                if resp:
                    on_token(resp)
                # Non-streaming (LLM outputs JSON; streaming raw JSON would look bad in UI).
                

            elif intent == "quiz_answer":
                session = handle_quiz_evaluate(session)
                resp = session.get("response", "")
                
                if resp:
                    on_token(resp)

            else:
                result = handle_qa(session)
                session = result

            _sessions[f"{student_id}:{course_id}"] = session
            elapsed = round((time.time() - start) * 1000)
            # Safe dict conversion
            temp_result = {
                "response": session.get("response", "Sorry, I could not process that. Please try again."),
                "agent_used": session.get("agent_used", "unknown"),
                "intent": session.get("intent", "unknown"),
                "metadata": session.get("metadata", {}),
                "elapsed_ms": elapsed,
            }
            if hasattr(temp_result, "model_dump"):
                temp_result = temp_result.model_dump()
            result_container["result"] = temp_result
        except Exception as e:  # noqa: BLE001
            # Log full traceback for debugging while still surfacing a concise message to the UI.
            print("[ERROR] chat_stream worker exception:\n" + traceback.format_exc())
            result_container["error"] = str(e)
            # Surface error in the stream so the UI doesn't hang.
            q.put(f"\n[ERROR] {str(e)}")
        finally:
            q.put(DONE)

    Thread(target=worker, daemon=True).start()

    def token_generator():
        while True:
            item = q.get()
            if item is DONE:
                return
            yield item

    return token_generator(), result_container


if __name__ == "__main__":
    tests = [
        ("hi there!",                           "greeting"),
        ("What is recursion?",                  "conceptual"),
        ("quiz me on loops",                    "quiz"),
        ("```python\nprint('hello')\n```",       "code"),
    ]
    for message, label in tests:
        print(f"\n[{label}] -> ", end="")
        result = chat("test_student", "python101", message)
        print(f"agent={result['agent_used']} intent={result['intent']}")
