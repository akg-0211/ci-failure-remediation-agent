import json
import re
import sys
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3"
HEAD_CHARS = 250      # from a very long line, keep this many characters from the start...
TAIL_CHARS = 250      # ...and this many from the end
MAX_RETRIES = 2       # how many times to re-ask the model if its answer has the wrong shape
REQUIRED_KEYS = {"category", "root_cause", "fix", "confidence"}

CATEGORIES = ["missing_dependency", "import_typo", "syntax_error",
              "port_mismatch", "dockerfile_error", "dependency_version_error",
              "config_error", "test_failure", "other"]

SYSTEM_PROMPT = f"""You are a CI/CD failure diagnosis assistant.
You will be given the relevant part of a failed GitHub Actions log for a Python FastAPI app built with Docker.
Find the root cause and suggest the smallest fix.
Reply ONLY with JSON in this exact shape:
{{"category": one of {CATEGORIES},
 "root_cause": "one or two sentences",
 "fix": "the exact change to make, naming the file",
 "confidence": a number between 0 and 1}}"""


def shorten(line: str) -> str:
    """Keep the start and the end of a very long line, cut the middle."""
    if len(line) <= HEAD_CHARS + TAIL_CHARS:
        return line
    return line[:HEAD_CHARS] + " ...[truncated]... " + line[-TAIL_CHARS:]


def extract_error_section(log: str, context: int = 5, max_chars: int = 6000) -> str:
    """Keep only the lines around errors, so the model reads less noise."""
    lines = log.splitlines()
    # remove GitHub timestamps like 2026-11-13T22:10:01.1234567Z
    lines = [re.sub(r"^\d{4}-\d{2}-\d{2}T\S+Z\s?", "", l) for l in lines]
    lines = [shorten(l) for l in lines]
    keywords = ("error", "exception", "traceback", "failed", "not found")
    hits = [i for i, l in enumerate(lines) if any(k in l.lower() for k in keywords)]
    if not hits:
        return "\n".join(lines[-80:])[-max_chars:]
    keep = set()
    for i in hits:
        keep.update(range(max(0, i - context), min(len(lines), i + context + 1)))
    section = "\n".join(lines[i] for i in sorted(keep))
    return section[-max_chars:]


def redact(text: str) -> str:
    """Hide tokens and passwords before the log goes to any model."""
    text = re.sub(r"gh[pousr]_[A-Za-z0-9]{20,}", "[REDACTED_GITHUB_TOKEN]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+", r"\1=[REDACTED]", text)
    return text


def is_valid(result) -> bool:
    """The model's answer must have all 4 keys, a known category, and confidence between 0 and 1."""
    return (
        isinstance(result, dict)
        and REQUIRED_KEYS <= result.keys()
        and result["category"] in CATEGORIES
        and isinstance(result["confidence"], (int, float))
        and 0 <= result["confidence"] <= 1
    )


def call_model(messages: list) -> str:
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def diagnose(log_text: str) -> dict:
    section = redact(extract_error_section(log_text))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Failed CI log:\n{section}"},
    ]
    for attempt in range(MAX_RETRIES + 1):
        try:
            raw = call_model(messages)
        except requests.RequestException as e:
            print(f"[attempt {attempt + 1}] model server error: {e}", file=sys.stderr)
            raw = ""
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = None
        if is_valid(result):
            return result
        print(f"[retry {attempt + 1}/{MAX_RETRIES}] invalid model output: {raw[:120]!r}", file=sys.stderr)
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Your reply did not match the required JSON shape. Reply ONLY with JSON with exactly these keys: "
            f"category (one of {CATEGORIES}), root_cause, fix, confidence (0 to 1)."
        )})
    return {"category": "other", "root_cause": "model never returned valid JSON", "fix": "", "confidence": 0.0}

def main():
    case_dir = Path(sys.argv[1])
    log_text = (case_dir / "log.txt").read_text(encoding="utf-8", errors="ignore")
    result = diagnose(log_text)
    print(json.dumps(result, indent=2))

    expected_file = case_dir / "expected.json"
    if expected_file.exists():
        expected = json.loads(expected_file.read_text(encoding="utf-8"))
        match = result.get("category") == expected["category"]
        print(f"\nExpected category: {expected['category']}  ->  {'MATCH' if match else 'MISMATCH'}")


if __name__ == "__main__":
    main()