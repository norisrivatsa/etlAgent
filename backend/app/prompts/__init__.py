from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


@lru_cache
def load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text().strip()
