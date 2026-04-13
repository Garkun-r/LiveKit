from pathlib import Path

PROMPT_FILE = Path(__file__).with_name("prompt.txt")

def get_active_prompt() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")

    content = PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError("Prompt file is empty")

    return content
