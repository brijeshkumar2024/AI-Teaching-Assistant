"""
agents/code_review_agent.py
────────────────────────────
Code review agent pipeline:
  1. Runs student code in the Docker sandbox (isolated, timed)
  2. Compares output against expected test cases
  3. LLM analyses correctness, style, and efficiency
  4. Returns constructive hints — never the full solution
  5. Runs plagiarism check in parallel
"""

import json
import time
import subprocess
from typing import Dict, List, Optional

from core.llm_config import get_llm
from core.plagiarism import check_plagiarism, register_submission
from core.memory import save_interaction

# ── Docker sandbox config ─────────────────────────────────────────────────
SANDBOX_IMAGE   = "ai-ta-sandbox"
SANDBOX_TIMEOUT = 15        # seconds before Docker itself kills container
MEMORY_LIMIT    = "128m"
CPU_QUOTA       = "50000"   # 50% of one CPU


# ── LLM feedback prompt ───────────────────────────────────────────────────
REVIEW_PROMPT_TEMPLATE = """You are a supportive programming instructor reviewing a student's code.
Your job is to give CONSTRUCTIVE feedback that helps the student LEARN — not to rewrite their code for them.

Assignment topic: {topic}

Student's code:
```python
{code}
```

Execution result:
- Exit code : {exit_code} (0 = success)
- Stdout    : {stdout}
- Stderr    : {stderr}
- Timed out : {timed_out}

Test case results:
{test_results}

Your review MUST cover all of these sections:

## Correctness
Did the code produce the expected output? If not, explain WHY it failed without giving the fix directly.

## Code Style
Comment on variable naming, readability, and PEP 8 compliance. Be specific.

## Efficiency
Is the approach reasonable? Mention Big-O only if relevant to the assignment level.

## Hints for Improvement
Give 2-3 specific, actionable hints. Use guiding questions like "What would happen if you tried X?" Do NOT write the corrected code.

## Encouragement
End with a short motivating message tailored to what the student did well.

Keep the total response under 400 words. Be warm, specific, and educational.
"""


# ── Docker sandbox runner ─────────────────────────────────────────────────

def is_docker_running() -> bool:
    '''Quick check if Docker daemon is accessible.'''
    try:
        subprocess.run(["docker", "ps", "--format", "json"], 
                       capture_output=True, timeout=2, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_in_sandbox(code: str) -> Dict:
    """
    Executes code in the Docker sandbox container.
    Falls back to in-process execution if Docker is unavailable (dev mode).

    Returns:
        { stdout, stderr, exit_code, timed_out, execution_mode }
    """
    payload = json.dumps({"code": code})

    if not is_docker_running():
        fallback = _dev_fallback_execute(code)
        fallback["stderr"] += "\n⚠️ Running in safe dev mode (Docker not available)"
        fallback["execution_mode"] = "docker_fallback"
        return fallback

    try:
        result = subprocess.run(
            [
                "docker", "run",
                "--rm",                          # auto-remove container after run
                "--network", "none",             # no internet access
                "--memory", MEMORY_LIMIT,        # RAM cap
                "--cpu-quota", CPU_QUOTA,        # CPU cap
                "--read-only",                   # read-only filesystem
                "--tmpfs", "/tmp:size=16m",      # tiny writable tmp
                "-i",                            # stdin mode
                SANDBOX_IMAGE,
            ],
            input=payload.encode(),
            capture_output=True,
            timeout=SANDBOX_TIMEOUT,
        )
        try:
            output = json.loads(result.stdout.decode())
            output["execution_mode"] = "docker"
            return output
        except json.JSONDecodeError:
            # If the sandbox didn't return valid JSON, fall back to the dev runner
            # so the student still gets actionable feedback instead of a hard error.
            fallback = _dev_fallback_execute(code)
            fallback["stderr"] = (
                f"Sandbox error: invalid JSON from container "
                f"(return code {result.returncode}, stdout: {result.stdout.decode()[:120] or '<empty>'}, "
                f"stderr: {result.stderr.decode()[:120] or '<empty>'}). "
                "Ran code locally instead for feedback."
            )
            fallback["execution_mode"] = "dev_fallback"
            return fallback

    except FileNotFoundError:
        # Docker not available — use dev fallback
        return _dev_fallback_execute(code)

    except subprocess.TimeoutExpired:
        return {
            "stdout"        : "",
            "stderr"        : f"Container forcefully killed after {SANDBOX_TIMEOUT}s.",
            "exit_code"     : 124,
            "timed_out"     : True,
            "execution_mode": "docker",
        }

    except Exception as e:
        return {
            "stdout"        : "",
            "stderr"        : f"Sandbox error: {str(e)}",
            "exit_code"     : 1,
            "timed_out"     : False,
            "execution_mode": "error",
        }


def _dev_fallback_execute(code: str) -> Dict:
    """
    In-process execution for local development (when Docker isn't running).
    WARNING: Not safe for production — use Docker in production.
    """
    import sys
    from io import StringIO
    import traceback

    stdout_buf = StringIO()
    stderr_buf = StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout_buf, stderr_buf

    exit_code = 0
    try:
        exec(compile(code, "<student_code>", "exec"), {"__name__": "__main__"})
    except Exception:
        traceback.print_exc()
        exit_code = 1
    finally:
        sys.stdout, sys.stderr = old_out, old_err

    return {
        "stdout"        : stdout_buf.getvalue()[:4000],
        "stderr"        : stderr_buf.getvalue()[:4000],
        "exit_code"     : exit_code,
        "timed_out"     : False,
        "execution_mode": "dev_fallback",
    }


# ── Test case evaluator ───────────────────────────────────────────────────

def _run_test_cases(
    code: str,
    test_cases: List[Dict],
) -> str:
    """
    Runs test cases by appending assertion code to student submission.
    Returns a human-readable test summary string.
    """
    if not test_cases:
        return "No test cases provided."

    results = []
    passed  = 0

    for i, tc in enumerate(test_cases, 1):
        test_code = code + "\n\n" + tc.get("assertion_code", "")
        exec_result = run_in_sandbox(test_code)

        ok = (
            exec_result["exit_code"] == 0
            and not exec_result["timed_out"]
            and tc.get("expected_output", "").strip() in exec_result["stdout"]
        )

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1

        results.append(
            f"Test {i} [{status}]: {tc.get('description', 'Unnamed test')}"
            + (f"\n  Expected : {tc.get('expected_output', '')}" if not ok else "")
            + (f"\n  Got      : {exec_result['stdout'].strip()[:200]}" if not ok else "")
        )

    summary = f"{passed}/{len(test_cases)} tests passed\n\n" + "\n".join(results)
    return summary


# ── Main agent function ───────────────────────────────────────────────────

def run_code_review_agent(
    student_id  : str,
    course_id   : str,
    code        : str,
    topic       : str = "General Python",
    test_cases  : Optional[List[Dict]] = None,
    stream: bool = False,
    token_callback=None,
    max_tokens: int = 700,
    max_retries: int = 3,
) -> Dict:
    """
    Full code review pipeline.

    Args:
        student_id : Student identifier
        course_id  : Course identifier
        code       : Student's submitted Python code
        topic      : Assignment topic (for context in feedback)
        test_cases : List of dicts with keys:
                       - description     : str
                       - assertion_code  : str  (appended to student code)
                       - expected_output : str

    Returns:
        {
            "feedback"         : str,
            "execution"        : dict,
            "test_summary"     : str,
            "tests_passed"     : int,
            "tests_total"      : int,
            "plagiarism"       : dict,
            "response_time_ms" : int,
        }
    """
    start = time.time()
    test_cases = test_cases or []

    # ── Step 1: Execute code in sandbox ──────────────────────────────────
    execution = run_in_sandbox(code)

    # ── Step 2: Run test cases ────────────────────────────────────────────
    test_summary = _run_test_cases(code, test_cases)
    tests_passed = test_summary.count("[PASS]")
    tests_total  = len(test_cases)

    # ── Step 3: Plagiarism check ──────────────────────────────────────────
    register_submission(student_id, course_id, code)
    plagiarism_result = check_plagiarism(student_id, course_id, code)

    # ── Step 4: LLM feedback ──────────────────────────────────────────────
    llm = get_llm(temperature=0.3, max_tokens=max_tokens, streaming=stream)
    prompt = REVIEW_PROMPT_TEMPLATE.format(
        topic        = topic,
        code         = code,
        exit_code    = execution["exit_code"],
        stdout       = execution["stdout"][:1000] or "(no output)",
        stderr       = execution["stderr"][:500]  or "(no errors)",
        timed_out    = execution["timed_out"],
        test_results = test_summary,
    )

    if not stream:
        response = llm.invoke(prompt)
        feedback = response.content.strip()
    else:
        from langchain_core.messages import HumanMessage
        tokens: List[str] = []
        for attempt in range(max_retries):
            try:
                tokens = []
                for chunk in llm.stream([HumanMessage(content=prompt)]):
                    token = getattr(chunk, "content", None) or getattr(chunk, "text", "")
                    if token:
                        tokens.append(token)
                        if token_callback:
                            token_callback(token)
                feedback = "".join(tokens).strip()
                break
            except Exception as e:  # noqa: BLE001
                err = str(e)
                if attempt < max_retries - 1 and any(x in err for x in ["429", "RESOURCE_EXHAUSTED", "quota", "rate_limit"]):
                    time.sleep([10, 30, 60][attempt])
                    continue
                raise

    # ── Step 5: Save to memory ────────────────────────────────────────────
    summary_for_memory = (
        f"[Code submission on '{topic}'] "
        f"Tests: {tests_passed}/{tests_total} passed. "
        f"AI Feedback given."
    )
    save_interaction(student_id, course_id, summary_for_memory, feedback)

    elapsed = round((time.time() - start) * 1000)

    return {
        "feedback"         : feedback,
        "execution"        : execution,
        "test_summary"     : test_summary,
        "tests_passed"     : tests_passed,
        "tests_total"      : tests_total,
        "plagiarism"       : plagiarism_result,
        "response_time_ms" : elapsed,
    }


if __name__ == "__main__":
    sample_code = """
def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)

print(factorial(5))
"""
    test_cases = [
        {
            "description"    : "factorial(5) should return 120",
            "assertion_code" : "assert factorial(5) == 120, 'Expected 120'",
            "expected_output": "120",
        },
        {
            "description"    : "factorial(0) should return 1",
            "assertion_code" : "assert factorial(0) == 1, 'Expected 1'",
            "expected_output": "1",
        },
    ]

    result = run_code_review_agent(
        student_id = "test_student",
        course_id  = "python101",
        code       = sample_code,
        topic      = "Recursion — factorial function",
        test_cases = test_cases,
    )

    print(result["feedback"])
    print(f"\nTests: {result['tests_passed']}/{result['tests_total']} passed")
    print(f"Plagiarism flagged: {result['plagiarism']['flagged']}")
