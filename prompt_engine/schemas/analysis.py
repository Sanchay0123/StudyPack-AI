"""Schemas for the analysis chain: P01 document understanding, P02 topic map,
P03 learning objectives, P04 teaching strategy."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DomainCategory = Literal[
    "mathematics", "physical_sciences", "life_sciences", "computer_science", "engineering",
    "humanities", "social_sciences", "business_management", "languages_literature", "arts",
    "law", "medicine_health", "other",
]


class TermDefinition(BaseModel):
    term: str = Field(description="Technical term exactly as used in the source")
    definition: str = Field(description="Short definition grounded in the source")


class DocumentAnalysis(BaseModel):
    """P01 output."""
    subject: str = Field(description="Specific subject or course name, e.g. 'Computer Networks'")
    domain_category: DomainCategory
    subject_context: str = Field(description="2-3 sentences: what this material covers and where it fits in the discipline")
    purpose: str = Field(description="What the material is for (lecture, revision, lab, reference...)")
    estimated_level: str = Field(description="Estimated academic level, e.g. 'first-year undergraduate'")
    major_concepts: list[str] = Field(description="The most important concepts, in teaching order", max_length=25)
    key_terms: list[TermDefinition] = Field(max_length=25)
    prerequisites: list[str] = Field(description="Knowledge a student needs before studying this", max_length=10)
    gaps: list[str] = Field(description="Material that seems missing, cut off, or only mentioned without explanation", max_length=10)
    overlaps: list[str] = Field(description="Content repeated across documents or sections", max_length=10)


class SubtopicItem(BaseModel):
    title: str
    description: str = Field(description="One sentence on what this subtopic covers")
    section_ids: list[str] = Field(description="IDs of the source sections (e.g. 'S4') that contain this subtopic")


class TopicItem(BaseModel):
    title: str
    description: str = Field(description="One or two sentences on what this topic covers")
    section_ids: list[str] = Field(description="Source section IDs that belong to this topic")
    subtopics: list[SubtopicItem] = Field(max_length=12)


class TopicMap(BaseModel):
    """P02 output."""
    topics: list[TopicItem] = Field(min_length=1, max_length=20)


class TopicObjectives(BaseModel):
    topic_title: str = Field(description="Exactly the topic title as given")
    objectives: list[str] = Field(description="3-6 measurable objectives starting with an action verb (explain, calculate, compare...)",
                                  min_length=1, max_length=8)
    prerequisites: list[str] = Field(max_length=6)


class LearningObjectives(BaseModel):
    """P03 output."""
    topics: list[TopicObjectives]


NoteSectionKind = Literal[
    "introduction", "background", "prerequisites", "concept", "definitions", "mechanism", "procedure",
    "formulas", "derivation", "algorithm", "syntax", "example", "applications", "advantages_disadvantages",
    "limitations", "comparison", "chronology", "causes_consequences", "significance", "mistakes",
    "key_points", "summary",
]


class TeachingStrategy(BaseModel):
    """P04 output."""
    domain_category: DomainCategory
    approach_summary: str = Field(description="2-3 sentences describing how this subject should be taught")
    priorities: list[str] = Field(description="What explanations must prioritise for this subject", min_length=3, max_length=10)
    note_sections: list[NoteSectionKind] = Field(description="Section kinds to use in lecture notes, in order", min_length=4, max_length=16)
    sections_to_omit: list[str] = Field(description="Section kinds that do not apply to this subject", max_length=10)
    example_style: Literal["quantitative", "programming", "conceptual", "case_study", "mixed"]
    example_types: list[str] = Field(description="Kinds of examples that suit this subject", max_length=6)
    question_types: list[str] = Field(description="Kinds of exam questions that suit this subject", max_length=7)
    diagram_types: list[str] = Field(description="Diagram kinds that help (flowchart, timeline, concept map...)", max_length=6)
    notation_guidance: str = Field(description="How to handle notation, formulas, code or terminology")
    common_pitfalls_focus: str = Field(description="What kinds of student mistakes to highlight")
