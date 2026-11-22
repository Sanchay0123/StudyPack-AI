"""Upload validation, sanitisation and safe storage.

Uploaded files are stored under data/uploads/<project_id>/<document_id><ext>;
the original (sanitised) filename is kept only as metadata, so user-supplied
names never become filesystem paths. Uploaded content is never executed.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from config.settings import Settings
from storage.models import Document, new_id
from storage.repository import Repository

SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".txt": "txt", ".md": "md", ".markdown": "md"}


class UploadError(Exception):
    pass


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = name.replace("\\", "/").split("/")[-1]  # drop any path component
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[^A-Za-z0-9._\- ()]", "_", name).strip(" .")
    name = re.sub(r"_+", "_", name)
    if not name or name.startswith("."):
        name = f"document{name}"
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: max_len - len(ext) - 1] + "." + ext) if dot else name[:max_len]
    return name


def detect_file_type(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted({e for e in SUPPORTED_EXTENSIONS if e != ".markdown"}))
        raise UploadError(f"'{filename}': unsupported file type '{ext or 'none'}'. Supported: {allowed}.")
    file_type = SUPPORTED_EXTENSIONS[ext]
    if not data:
        raise UploadError(f"'{filename}' is empty.")
    if file_type == "pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise UploadError(f"'{filename}' has a .pdf extension but is not a PDF file.")
    if file_type in ("docx", "pptx") and not data.startswith(b"PK\x03\x04"):
        raise UploadError(f"'{filename}' is not a valid Office Open XML ({file_type}) file. "
                          "Legacy .doc/.ppt files must be re-saved as .docx/.pptx.")
    if file_type in ("txt", "md") and b"\x00" in data[:8192]:
        raise UploadError(f"'{filename}' appears to be binary, not text.")
    return file_type


@dataclass
class UploadOutcome:
    document: Document
    duplicate: bool


def store_upload(repo: Repository, settings: Settings, project_id: str, filename: str, data: bytes) -> UploadOutcome:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise UploadError(f"'{filename}' is {len(data) / 1e6:.1f} MB; the limit is {settings.max_upload_mb} MB.")
    file_type = detect_file_type(filename, data)
    safe_name = sanitize_filename(filename)
    sha = hashlib.sha256(data).hexdigest()
    existing = repo.find_document_by_hash(project_id, sha)
    if existing:
        return UploadOutcome(existing, duplicate=True)

    document_id = new_id("doc_")
    target_dir = (settings.uploads_dir / project_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = (target_dir / f"{document_id}{Path(safe_name).suffix.lower()}").resolve()
    if target_dir not in target.parents:  # defence in depth against traversal
        raise UploadError("Refusing to write outside the uploads directory.")
    target.write_bytes(data)
    doc = Document(document_id=document_id, project_id=project_id, filename=safe_name, file_type=file_type,
                   storage_path=str(target), sha256=sha, size_bytes=len(data))
    repo.add_document(doc)
    return UploadOutcome(doc, duplicate=False)
