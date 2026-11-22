"""Domain records shared by ingestion, analysis, generation and the UI."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Project(BaseModel):
    project_id: str = Field(default_factory=lambda: new_id("prj_"))
    name: str
    subject: str | None = None
    academic_level: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class Document(BaseModel):
    document_id: str = Field(default_factory=lambda: new_id("doc_"))
    project_id: str
    filename: str
    file_type: str
    storage_path: str
    sha256: str
    size_bytes: int
    processing_status: str = "uploaded"  # uploaded | extracted | needs_ocr | failed
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class ContentChunk(BaseModel):
    """Normalized, format-independent unit of source content."""
    chunk_id: str
    document_id: str
    project_id: str
    document_name: str = ""
    seq: int
    content: str
    content_type: str = "text"  # text | list | table | code | equation | slide_notes | mixed
    page_number: int | None = None
    slide_number: int | None = None
    heading: str | None = None
    section_id: str | None = None
    source_reference: str
    extraction_confidence: float = 1.0
    needs_review: bool = False


class Topic(BaseModel):
    topic_id: str = Field(default_factory=lambda: new_id("top_"))
    project_id: str
    parent_topic_id: str | None = None
    title: str
    description: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list)
    order_index: int = 0


class Resource(BaseModel):
    resource_id: str = Field(default_factory=lambda: new_id("res_"))
    project_id: str
    topic_id: str | None
    resource_type: str
    version: int = 1
    is_current: bool = True
    content: dict[str, Any]
    prompt_id: str | None = None
    prompt_version: str | None = None
    provider: str | None = None
    model: str | None = None
    origin: str = "generated"  # generated | refined | edited
    created_at: str = Field(default_factory=now_iso)


class GenerationTask(BaseModel):
    task_id: str = Field(default_factory=lambda: new_id("tsk_"))
    project_id: str
    topic_id: str | None
    resource_type: str
    status: str = "pending"  # pending | running | done | failed | interrupted
    attempts: int = 0
    error: str | None = None
    updated_at: str = Field(default_factory=now_iso)


class EvaluationRecord(BaseModel):
    evaluation_id: str = Field(default_factory=lambda: new_id("evl_"))
    project_id: str
    topic_id: str | None
    resource_id: str | None
    coverage_score: float | None
    report: dict[str, Any]
    evaluation_status: str  # passed | needs_refinement | failed
    created_at: str = Field(default_factory=now_iso)


class StageRun(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run_"))
    project_id: str | None
    stage_id: str
    prompt_version: str | None
    provider: str | None
    model: str | None
    attempts: int
    success: bool
    duration_s: float | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    created_at: str = Field(default_factory=now_iso)
