"""Ingestion pipeline: store -> extract -> normalize -> persist."""
from __future__ import annotations

from dataclasses import dataclass, field

from config.logging_config import get_logger
from config.settings import Settings, get_settings
from ingestion.docx_extractor import extract_docx
from ingestion.normalizer import normalize
from ingestion.pdf_extractor import extract_pdf
from ingestion.pptx_extractor import extract_pptx
from ingestion.text_extractor import extract_text
from ingestion.types import ExtractionError, ExtractionResult
from ingestion.upload_handler import UploadError, store_upload
from storage.models import Document
from storage.repository import Repository

log = get_logger("ingestion")


def extract_document(doc: Document, use_ocr: bool = False) -> ExtractionResult:
    if doc.file_type == "pdf":
        return extract_pdf(doc.storage_path, use_ocr=use_ocr)
    if doc.file_type == "docx":
        return extract_docx(doc.storage_path)
    if doc.file_type == "pptx":
        return extract_pptx(doc.storage_path)
    if doc.file_type in ("txt", "md"):
        return extract_text(doc.storage_path, markdown=doc.file_type == "md")
    raise ExtractionError(f"No extractor for file type {doc.file_type}")


@dataclass
class FileReport:
    filename: str
    status: str  # extracted | needs_ocr | failed | rejected | duplicate
    message: str = ""
    chunks: int = 0
    warnings: list[str] = field(default_factory=list)
    document_id: str | None = None


def process_document(repo: Repository, doc: Document, settings: Settings, use_ocr: bool = False) -> FileReport:
    try:
        result = extract_document(doc, use_ocr=use_ocr)
    except ExtractionError as exc:
        repo.update_document_status(doc.document_id, "failed", {**doc.metadata, "error": str(exc)})
        log.warning("Extraction failed for %s: %s", doc.filename, exc)
        return FileReport(doc.filename, "failed", str(exc), document_id=doc.document_id)
    except Exception as exc:  # noqa: BLE001 - never let one file break the batch
        repo.update_document_status(doc.document_id, "failed", {**doc.metadata, "error": f"Unexpected error: {exc}"})
        log.exception("Unexpected extraction failure for %s", doc.filename)
        return FileReport(doc.filename, "failed", f"Unexpected extraction error: {exc}", document_id=doc.document_id)

    chunks = normalize(result.blocks, document_id=doc.document_id, project_id=doc.project_id,
                       document_name=doc.filename, target_chars=settings.chunk_target_chars)
    repo.replace_chunks(doc.document_id, chunks)
    status = "needs_ocr" if result.needs_ocr else "extracted"
    if not chunks:
        status = "needs_ocr" if result.needs_ocr else "failed"
    metadata = {**result.metadata, "warnings": result.warnings, "chunks": len(chunks), "chars": result.text_chars,
                "ocr_applied": result.ocr_applied, "needs_review_chunks": sum(c.needs_review for c in chunks)}
    repo.update_document_status(doc.document_id, status, metadata)
    message = f"{len(chunks)} chunks, {result.text_chars:,} characters"
    if status == "failed":
        message = "No extractable text found."
    log.info("Extracted %s: %s (%s)", doc.filename, message, status)
    return FileReport(doc.filename, status, message, len(chunks), result.warnings, doc.document_id)


def ingest_files(repo: Repository, project_id: str, files: list[tuple[str, bytes]], use_ocr: bool = False,
                 settings: Settings | None = None) -> list[FileReport]:
    settings = settings or get_settings()
    reports = []
    for filename, data in files:
        try:
            outcome = store_upload(repo, settings, project_id, filename, data)
        except UploadError as exc:
            reports.append(FileReport(filename, "rejected", str(exc)))
            continue
        if outcome.duplicate:
            reports.append(FileReport(filename, "duplicate", f"Already uploaded as '{outcome.document.filename}'; skipped.",
                                      document_id=outcome.document.document_id))
            continue
        reports.append(process_document(repo, outcome.document, settings, use_ocr=use_ocr))
    ok = [r for r in reports if r.status in ("extracted", "needs_ocr")]
    if ok:
        repo.log_activity(project_id, f"Ingested {len(ok)} document(s)")
        repo.touch_project(project_id)
    return reports
