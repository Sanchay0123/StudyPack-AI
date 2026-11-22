"""Routes a task to its prompt template and selects task-specific few-shot material.

Routing decisions are data-driven (resource type + teaching strategy), so new
subjects need no new code: the strategy produced by P04 picks the examples
style, and the router picks the matching few-shot block.
"""
from __future__ import annotations

from prompt_engine.template_loader import load_fewshot

RESOURCE_TYPES = ["notes", "examples", "questions", "revision", "flashcards", "diagrams", "quiz"]

RESOURCE_LABELS = {
    "notes": "Lecture notes", "examples": "Worked examples", "questions": "Important questions",
    "revision": "Revision notes", "flashcards": "Flashcards", "diagrams": "Diagrams", "quiz": "Practice quiz",
}

RESOURCE_TEMPLATES = {
    "notes": "lecture_notes", "examples": "examples", "questions": "important_questions",
    "revision": "revision_notes", "flashcards": "flashcards", "diagrams": "diagrams", "quiz": "quizzes",
}

_DOMAIN_TO_EXAMPLE_STYLE = {
    "mathematics": "quantitative", "physical_sciences": "quantitative", "engineering": "quantitative",
    "computer_science": "programming", "business_management": "case_study", "law": "case_study",
}


def template_for(resource_type: str) -> str:
    if resource_type not in RESOURCE_TEMPLATES:
        raise ValueError(f"Unknown resource type {resource_type!r}")
    return RESOURCE_TEMPLATES[resource_type]


def example_style(strategy: dict | None) -> str:
    strategy = strategy or {}
    style = strategy.get("example_style") or "conceptual"
    if style == "mixed":
        style = _DOMAIN_TO_EXAMPLE_STYLE.get(strategy.get("domain_category", ""), "conceptual")
    return style


def fewshot_for(resource_type: str, strategy: dict | None = None) -> str:
    if resource_type == "examples":
        return load_fewshot(f"examples_{example_style(strategy)}")
    if resource_type == "questions":
        return load_fewshot("questions")
    if resource_type == "flashcards":
        return load_fewshot("flashcards")
    if resource_type == "diagrams":
        return load_fewshot("mermaid")
    if resource_type == "strategy":
        return load_fewshot("teaching_strategies")
    return ""
