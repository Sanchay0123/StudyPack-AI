"""Schemas for generated learning resources (P05-P10)."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from prompt_engine.schemas.analysis import NoteSectionKind

Provenance = Literal["source", "supplementary", "inferred"]
Difficulty = Literal["easy", "medium", "hard"]

PROVENANCE_HELP = ("'source' = stated in the source material; 'supplementary' = standard background knowledge "
                   "added to aid understanding; 'inferred' = your interpretation or uncertain")


# ----------------------------------------------------------------- P05 notes
class NoteSection(BaseModel):
    heading: str
    kind: NoteSectionKind
    content: str = Field(description="Detailed explanation in Markdown (paragraphs, bullet lists, tables, $LaTeX$, code blocks); usually 120-300 words")
    provenance: Provenance = Field(description=PROVENANCE_HELP)
    source_labels: list[str] = Field(description="Source labels (e.g. 'S2') supporting this section; empty if supplementary")


class KeyTerm(BaseModel):
    term: str
    definition: str
    source_labels: list[str] = Field(default_factory=list)


class LectureNotes(BaseModel):
    topic_title: str
    overview: str = Field(description="2-4 sentence introduction to the topic")
    sections: list[NoteSection] = Field(min_length=5, max_length=20)
    key_terms: list[KeyTerm] = Field(max_length=20)
    summary: str = Field(description="Concise topic summary paragraph")


# -------------------------------------------------------------- P06 examples
class WorkedExample(BaseModel):
    title: str
    example_type: str = Field(description="numerical, worked problem, code walkthrough, real-world application, case study, illustration...")
    problem: str = Field(description="The problem statement or scenario")
    steps: list[str] = Field(description="Step-by-step solution or walkthrough; each step explains why", min_length=1)
    answer: str = Field(description="Final answer, result or conclusion")
    explanation: str = Field(description="What the example teaches and how it connects to the concept")
    provenance: Provenance = Field(description=PROVENANCE_HELP)
    source_labels: list[str] = Field(default_factory=list)


class ExampleSet(BaseModel):
    examples: list[WorkedExample] = Field(min_length=1, max_length=6)


# ------------------------------------------------------------- P07 questions
QuestionType = Literal["short_answer", "long_answer", "conceptual", "application", "analytical", "numerical", "programming"]


class ExamQuestion(BaseModel):
    question: str
    question_type: QuestionType
    difficulty: Difficulty
    model_answer: str = Field(description="Model answer or answer guidance a student can check against")
    key_points: list[str] = Field(description="Points an examiner would look for", max_length=8)
    source_labels: list[str] = Field(default_factory=list)


class QuestionSet(BaseModel):
    questions: list[ExamQuestion] = Field(min_length=3, max_length=15)


# -------------------------------------------------------------- P08 revision
class Formula(BaseModel):
    name: str
    expression: str = Field(description="Formula exactly as in the source (LaTeX allowed)")
    meaning: str = Field(description="What each symbol means / when to use it")


class Difference(BaseModel):
    items: str = Field(description="What is compared, e.g. 'TCP vs UDP'")
    difference: str


class Process(BaseModel):
    name: str
    steps: list[str] = Field(min_length=2)


class Definition(BaseModel):
    term: str
    definition: str


class RevisionNotes(BaseModel):
    one_line_summary: str
    key_definitions: list[Definition] = Field(max_length=15)
    key_concepts: list[str] = Field(description="Short bullet statements of essential ideas", min_length=3, max_length=15)
    formulas: list[Formula] = Field(description="Empty list if the topic has no formulas", max_length=12)
    relationships: list[str] = Field(description="Important cause/effect or dependency relationships", max_length=10)
    differences: list[Difference] = Field(max_length=8)
    processes: list[Process] = Field(max_length=6)
    common_mistakes: list[str] = Field(max_length=8)


class Flashcard(BaseModel):
    question: str = Field(description="A focused recall or understanding question (not a paragraph)")
    answer: str = Field(description="Concise answer, at most 2-3 sentences")
    difficulty: Difficulty
    source_labels: list[str] = Field(default_factory=list)


class FlashcardSet(BaseModel):
    cards: list[Flashcard] = Field(min_length=4, max_length=20)


# -------------------------------------------------------------- P09 diagrams
MERMAID_STARTS = ("flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram", "stateDiagram-v2",
                  "erDiagram", "timeline", "mindmap", "pie", "gantt", "journey", "quadrantChart")


UNSAFE_LABEL_CHARS = '()<>;|#'


def quote_flowchart_labels(code: str) -> str:
    """Mechanically quote unquoted [..] / {..} flowchart labels that contain parser-breaking characters.

    `A[Label (x)]` -> `A["Label (x)"]`. Meaning-preserving normalisation, so repair attempts are not
    spent on pure syntax.
    """
    def fix(match: re.Match) -> str:
        node, open_, inner, close = match.groups()
        stripped = inner.strip()
        if stripped.startswith('"') and stripped.endswith('"'):
            return match.group(0)
        if any(ch in stripped for ch in UNSAFE_LABEL_CHARS):
            return f'{node}{open_}"{stripped.replace(chr(34), chr(39))}"{close}'
        return match.group(0)

    code = re.sub(r"(\b[A-Za-z0-9_]+)(\[)([^\[\]\n]*)(\])", fix, code)
    return re.sub(r"(\b[A-Za-z0-9_]+)(\{)([^{}\n]*)(\})", fix, code)


def check_mermaid(code: str) -> str:
    code = code.strip()
    code = re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", code).strip()
    first = code.split("\n", 1)[0].strip()
    if first.startswith(("flowchart", "graph")):
        code = quote_flowchart_labels(code)
    if not any(first.startswith(k) for k in MERMAID_STARTS):
        raise ValueError(f"Mermaid code must start with a diagram type such as {', '.join(MERMAID_STARTS[:6])}; got '{first[:40]}'")
    if code.count("[") != code.count("]") or code.count("(") != code.count(")") or code.count("{") != code.count("}"):
        raise ValueError("Mermaid code has unbalanced brackets")
    lines = [ln for ln in code.split("\n")[1:] if ln.strip()]
    if not lines:
        raise ValueError("Mermaid diagram has no content")
    if first.startswith(("flowchart", "graph")) and "-->" not in code and "---" not in code and "-.->" not in code and "==>" not in code:
        raise ValueError("Flowchart has no edges (use A --> B)")
    if first.startswith(("flowchart", "graph", "mindmap")):
        # Unquoted labels containing brackets/special characters break the Mermaid parser.
        for label in re.findall(r"\[([^\]\[]*)\]", code):
            inner = label.strip()
            if inner.startswith('"') and inner.endswith('"'):
                continue
            if any(ch in inner for ch in UNSAFE_LABEL_CHARS + '[]{}"'):
                raise ValueError(f"Mermaid label [{inner[:40]}] contains special characters; wrap it in double quotes: [\"...\"]")
    if re.search(r"(?m)^\s*(S\d+)\s*[\[(]", code) and first.startswith("mindmap"):
        raise ValueError("Do not use source labels (S1, S2...) as mindmap node IDs; write plain node text")
    return code


class Diagram(BaseModel):
    title: str
    diagram_type: str = Field(description="flowchart, concept map, timeline, sequence, hierarchy, process...")
    mermaid: str = Field(description="Valid Mermaid source code. Quote labels containing special characters: A[\"Label (x)\"]")
    caption: str = Field(description="What the diagram shows and how to read it")
    provenance: Provenance = Field(default="source", description=PROVENANCE_HELP)

    @field_validator("mermaid")
    @classmethod
    def _valid_mermaid(cls, v: str) -> str:
        return check_mermaid(v)


class DiagramSet(BaseModel):
    diagrams: list[Diagram] = Field(max_length=4)
    no_diagram_reason: str = Field(default="", description="If no diagram suits the topic, explain why and return an empty list")


# ------------------------------------------------------------------ P10 quiz
QuizType = Literal["mcq", "multi_select", "true_false", "short_answer", "application"]


class QuizQuestion(BaseModel):
    question: str
    question_type: QuizType
    options: list[str] = Field(description="Answer options; ['True','False'] for true_false; empty for short_answer/application")
    correct_answers: list[str] = Field(description="Correct option text(s) copied exactly from options; for short_answer/application, the model answer", min_length=1)
    explanation: str = Field(description="Why the answer is correct and why distractors are wrong")
    difficulty: Difficulty
    source_labels: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "QuizQuestion":
        def norm(s: str) -> str:
            return " ".join(s.strip().lower().split())

        if self.question_type == "true_false":
            self.options = ["True", "False"]
            fixed = []
            for a in self.correct_answers:
                if norm(a) in ("true", "t", "yes"):
                    fixed.append("True")
                elif norm(a) in ("false", "f", "no"):
                    fixed.append("False")
            if len(fixed) != 1:
                raise ValueError("true_false questions need exactly one answer: 'True' or 'False'")
            self.correct_answers = fixed
        elif self.question_type in ("mcq", "multi_select"):
            if len(self.options) < 3:
                raise ValueError(f"{self.question_type} questions need at least 3 options")
            if len({norm(o) for o in self.options}) != len(self.options):
                raise ValueError("options must be distinct")
            lookup = {norm(o): o for o in self.options}
            mapped = []
            for a in self.correct_answers:
                key = norm(a)
                if key not in lookup:
                    # allow letter answers like "B"
                    if len(key) == 1 and "a" <= key <= chr(ord("a") + len(self.options) - 1):
                        mapped.append(self.options[ord(key) - ord("a")])
                        continue
                    raise ValueError(f"correct answer '{a}' is not one of the options")
                mapped.append(lookup[key])
            self.correct_answers = list(dict.fromkeys(mapped))
            if self.question_type == "multi_select" and len(self.correct_answers) == 1:
                # A "select all that apply" question with exactly one correct option is a valid
                # single-answer question; normalise rather than spend repair attempts on the label.
                self.question_type = "mcq"
            if self.question_type == "mcq" and len(self.correct_answers) != 1:
                raise ValueError("mcq questions need exactly one correct answer (use multi_select for several)")
            if self.question_type == "multi_select" and len(self.correct_answers) < 2:
                raise ValueError("multi_select questions need at least two correct answers")
        else:
            self.options = []
        return self


class Quiz(BaseModel):
    questions: list[QuizQuestion] = Field(min_length=4, max_length=15)
