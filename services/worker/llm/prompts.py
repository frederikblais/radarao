"""Chargement des prompts versionnés (docs/prompts/). Aucun prompt codé en dur ailleurs."""

import os
import re
from functools import lru_cache
from pathlib import Path

_DEFAULT_DIR = Path(__file__).resolve().parents[3] / "docs" / "prompts"


def prompts_dir() -> Path:
    return Path(os.environ.get("PROMPTS_DIR", _DEFAULT_DIR))


@lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    """Retourne le corps du prompt (sans l'en-tête YAML de version)."""
    text = (prompts_dir() / f"{name}.md").read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()


def prompt_version(name: str) -> str:
    text = (prompts_dir() / f"{name}.md").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*(\S+)", text, flags=re.M)
    return m.group(1) if m else "0"


def render(name: str, **values: str) -> str:
    body = load_prompt(name)
    for k, v in values.items():
        body = body.replace("{{" + k + "}}", v)
    return body
