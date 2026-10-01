"""Load config/categories.yaml and suggest close matches for unknown categories."""

from __future__ import annotations

import difflib
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class UnknownCategory(Exception):
    def __init__(self, name: str, suggestions: list[str]) -> None:
        self.name = name
        self.suggestions = suggestions
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        super().__init__(f"Unknown category '{name}'.{hint} Run 'leadharvest categories'.")


class Category(BaseModel):
    key: str
    label: str
    osm_tags: list[str]
    synonyms: list[str] = Field(default_factory=list)

    @field_validator("osm_tags")
    @classmethod
    def _tags_have_values(cls, tags: list[str]) -> list[str]:
        for tag in tags:
            k, _, v = tag.partition("=")
            if not k or not v:
                raise ValueError(f"osm tag must be key=value, got {tag!r}")
        return tags


def default_categories_path() -> Path:
    cwd_path = Path("config/categories.yaml")
    if cwd_path.is_file():
        return cwd_path
    return Path(__file__).resolve().parents[2] / "config" / "categories.yaml"


def load_categories(path: Path | None = None) -> dict[str, Category]:
    path = path or default_categories_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {key: Category(key=key, **value) for key, value in data.items()}


def resolve_category(name: str, categories: dict[str, Category]) -> Category:
    wanted = name.strip().lower().replace("-", "_")
    if wanted in categories:
        return categories[wanted]
    for cat in categories.values():
        names = [cat.label.lower(), *(s.lower() for s in cat.synonyms)]
        if wanted.replace("_", " ") in names:
            return cat
    choices: dict[str, str] = {}
    for cat in categories.values():
        for alias in (cat.key, cat.label.lower(), *(s.lower() for s in cat.synonyms)):
            choices[alias] = cat.key
    close = difflib.get_close_matches(wanted.replace("_", " "), list(choices), n=5, cutoff=0.6)
    suggestions = list(dict.fromkeys(choices[c] for c in close))[:3]
    raise UnknownCategory(name, suggestions)
