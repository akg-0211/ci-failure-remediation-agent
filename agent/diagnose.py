import json
import re
import sys
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3"

CATEGORIES = ["missing_dependency", "import_typo", "syntax_error",
              "test_failure", "config_error", "other"]

SYSTEM_PROMPT = f"""You are a CI/CD failure diagnosis assistant.
You will be given the relevant part of a failed GitHub Actions log for a Python FastAPI app built with Docker.
Find the root cause and suggest the smallest fix.
Reply ONLY with JSON in this exact shape:
{{"category": one of {CATEGORIES},
 "root_cause": "one or two sentences",
 "fix": "the exact change to make, naming the file",
 "confidence": a number between 0 and 1}}"""


def extract_error_section(log: str, context: int = 5, max_chars: int = 6000) -> str:
    """Keep only the lines around errors, so the model reads less noise."""
    lines = log.splitlines()
    # remove GitHub timestamps like 2026-11-13T22:10:01.1234567Z
    lines = [re.sub(r"^\d{4}-\d{2}-\d{2}T\S+Z\s?", "", l) for l in lines]
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


def diagnose(log_text: str) -> dict:
    section = redact(extract_error_section(log_text))
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Failed CI log:\n{section}"},
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
    resp.raise_for_status()
    return json.loads(resp.json()["message"]["content"])


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