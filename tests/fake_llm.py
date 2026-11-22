"""TEST FIXTURE: a scripted LLM provider returning canned JSON per prompt template.

Used only by offline tests to exercise the prompt chain deterministically.
It is never used by the application.
"""
from __future__ import annotations

import json
import re

from providers.base import BaseLLMProvider, GenerationRequest, GenerationResult, ProviderStatus

NOTE_SECTION = {"heading": "How Things Work", "kind": "concept", "provenance": "source", "source_labels": ["S1"],
                "content": "Bus topology shares one backbone cable between all devices. A break in the backbone stops the network. "
                           "Star topology connects every device to a central switch, so one failed cable affects only one device."}

CANNED = {
    "document_analysis": {"subject": "Computer Networks", "domain_category": "computer_science",
                          "subject_context": "Introductory networking.", "purpose": "lecture", "estimated_level": "first-year",
                          "major_concepts": ["topology"], "key_terms": [{"term": "LAN", "definition": "local network"}],
                          "prerequisites": [], "gaps": [], "overlaps": []},
    "topic_mapping": {"topics": [{"title": "LAN Topologies", "description": "Ways to connect devices.", "section_ids": ["S1"],
                                  "subtopics": [{"title": "Bus topology", "description": "single cable", "section_ids": ["S1"]},
                                                {"title": "Star topology", "description": "central switch", "section_ids": ["S1"]}]}]},
    "learning_objectives": {"topics": [{"topic_title": "LAN Topologies", "objectives": ["Compare bus and star topologies"], "prerequisites": []}]},
    "teaching_strategy": {"domain_category": "computer_science", "approach_summary": "Concepts then comparisons.",
                          "priorities": ["concepts", "comparisons", "failures"], "note_sections": ["introduction", "concept", "comparison", "summary"],
                          "sections_to_omit": ["chronology"], "example_style": "programming", "example_types": ["scenario"],
                          "question_types": ["conceptual"], "diagram_types": ["flowchart"], "notation_guidance": "none",
                          "common_pitfalls_focus": "single points of failure"},
    "lecture_notes": {"topic_title": "LAN Topologies", "overview": "Topologies describe how devices connect.",
                      "sections": [dict(NOTE_SECTION, heading=f"Section {i}") for i in range(5)],
                      "key_terms": [{"term": "Bus", "definition": "shared backbone", "source_labels": ["S1", "S99"]}],
                      "summary": "Bus and star differ in failure behaviour."},
    "examples": {"examples": [{"title": "Cable break", "example_type": "scenario", "problem": "What happens if the bus breaks?",
                               "steps": ["The backbone carries all traffic."], "answer": "The network stops.",
                               "explanation": "Single point of failure.", "provenance": "source", "source_labels": ["S1"]}]},
    "important_questions": {"questions": [{"question": f"Q{i}?", "question_type": "conceptual", "difficulty": "easy",
                                           "model_answer": "A", "key_points": ["a"], "source_labels": ["S1"]} for i in range(3)]},
    "revision_notes": {"one_line_summary": "Topologies.", "key_definitions": [{"term": "Bus", "definition": "shared cable"}],
                       "key_concepts": ["a", "b", "c"], "formulas": [], "relationships": [], "differences": [], "processes": [],
                       "common_mistakes": []},
    "flashcards": {"cards": [{"question": f"Card {i}?", "answer": "Answer.", "difficulty": "easy", "source_labels": ["S1"]} for i in range(4)]},
    "diagrams": {"diagrams": [{"title": "Star", "diagram_type": "flowchart", "mermaid": "flowchart TD\n A[\"Switch\"] --> B[\"PC 1\"]",
                               "caption": "Star layout", "provenance": "source"}], "no_diagram_reason": ""},
    "quizzes": {"questions": [{"question": f"Quiz {i}?", "question_type": "mcq", "options": ["Bus", "Star", "Ring", "Mesh"],
                               "correct_answers": ["Star"], "explanation": "Central switch.", "difficulty": "easy",
                               "source_labels": ["S1"]} for i in range(4)]},
    "quality_evaluation": {"coverage": [{"subtopic": "Bus topology", "status": "covered", "evidence_quote": "Bus topology shares one backbone cable between all devices"},
                                        {"subtopic": "Star topology", "status": "covered", "evidence_quote": "this quote is not in the notes at all"}],
                           "unsupported_claims": [], "mislabelled_provenance": [], "factual_concerns": [], "structural_issues": [],
                           "readability": 4, "subject_relevance": 4, "corrections": [], "verdict": "pass"},
    "refinement": {"revisions": [{"action": "add", "target_heading": "END",
                                  "section": dict(NOTE_SECTION, heading="Star Topology Explained",
                                                  content="Star topology connects every device to a central switch.")}],
                   "change_log": ["Added star topology section"]},
}


class FakeLLM(BaseLLMProvider):
    name = "fake"

    def __init__(self, overrides: dict | None = None, broken_first: set[str] | None = None):
        self.overrides = overrides or {}
        self.broken_first = set(broken_first or ())  # templates whose first attempt returns invalid output
        self.calls: list[GenerationRequest] = []

    def _template(self, request: GenerationRequest) -> str:
        label = request.metadata.get("template", "")
        m = re.match(r"\w+:(\w+)@", label)
        return m.group(1) if m else ""

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        name = self._template(request)
        if name in self.broken_first:
            self.broken_first.discard(name)
            return GenerationResult('{"not": "valid for schema"', "fake", "fake-model", 0.01)
        payload = self.overrides.get(name, CANNED.get(name))
        if callable(payload):  # dynamic fixture: computes a response from the request
            payload = payload(request)
        if payload is None:
            return GenerationResult("plain text notes", "fake", "fake-model", 0.01)
        return GenerationResult(json.dumps(payload), "fake", "fake-model", 0.01, prompt_tokens=100, output_tokens=50)

    def is_available(self) -> ProviderStatus:
        return ProviderStatus("fake", True, "fake-model", "test fixture")

    def get_model_info(self):
        return {"provider": "fake"}
