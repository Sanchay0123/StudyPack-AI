"""Schemas for independent evaluation (P11) and targeted refinement (P12)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from prompt_engine.schemas.resources import NoteSection


class CoverageItem(BaseModel):
    subtopic: str = Field(description="Subtopic title exactly as listed")
    status: Literal["covered", "partial", "missing"] = Field(
        description="covered = essential concepts actually explained; partial = mentioned or thin; missing = absent")
    evidence_quote: str = Field(description="A short verbatim quote (5-20 words) from the NOTES proving coverage; empty if missing")


class UnsupportedClaim(BaseModel):
    claim: str = Field(description="The claim, quoted or closely paraphrased from the notes")
    section: str = Field(description="Heading of the notes section containing it")
    reason: str = Field(description="Why it is not supported by the source material")
    severity: Literal["low", "medium", "high"]


class Correction(BaseModel):
    section: str = Field(description="Heading of the section to fix, or 'NEW' to add a section")
    problem: str
    instruction: str = Field(description="Precise instruction for fixing it")


class NotesEvaluation(BaseModel):
    """P11 output."""
    coverage: list[CoverageItem]
    unsupported_claims: list[UnsupportedClaim] = Field(max_length=12)
    mislabelled_provenance: list[str] = Field(description="Sections marked 'source' that contain mostly non-source content", max_length=8)
    factual_concerns: list[str] = Field(description="Statements that look factually wrong or contradict the source", max_length=8)
    structural_issues: list[str] = Field(max_length=8)
    readability: int = Field(ge=1, le=5, description="1 = very hard to follow, 5 = clear and well-organised")
    subject_relevance: int = Field(ge=1, le=5, description="How well the explanations suit the subject's teaching style")
    corrections: list[Correction] = Field(max_length=10)
    verdict: Literal["pass", "needs_refinement"]


class TopicJudgement(BaseModel):
    topic: str
    adequately_covered: bool
    note: str = Field(description="Very short justification")


class ExperimentJudgement(BaseModel):
    """X03 output: rubric scores for the prompt-engineering experiment."""
    topic_coverage: list[TopicJudgement]
    completeness: int = Field(ge=1, le=5)
    completeness_reason: str
    source_fidelity: int = Field(ge=1, le=5)
    source_fidelity_reason: str
    readability: int = Field(ge=1, le=5)
    readability_reason: str
    relevance: int = Field(ge=1, le=5)
    relevance_reason: str
    unsupported_claims: list[str] = Field(max_length=15)


class SectionRevision(BaseModel):
    action: Literal["replace", "add", "remove"]
    target_heading: str = Field(description="Existing heading to replace/remove; for 'add', the heading to insert after (or 'END')")
    section: NoteSection | None = Field(default=None, description="The new or replacement section (null for remove)")


class NotesRefinement(BaseModel):
    """P12 output: targeted section-level edits, not a full rewrite."""
    revisions: list[SectionRevision] = Field(min_length=1, max_length=10)
    change_log: list[str] = Field(description="One line per change explaining what was fixed", min_length=1)
