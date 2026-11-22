"""Data-access layer. All SQL lives here."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterable

from storage.database import Database, get_database
from storage.models import (
    ContentChunk,
    Document,
    EvaluationRecord,
    GenerationTask,
    Project,
    Resource,
    StageRun,
    Topic,
    now_iso,
)


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class Repository:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    @property
    def conn(self):
        return self.db.connect()

    # ---------------------------------------------------------------- projects
    def create_project(self, project: Project) -> Project:
        self.conn.execute(
            "INSERT INTO projects VALUES (?,?,?,?,?,?,?)",
            (project.project_id, project.name, project.subject, project.academic_level,
             _j(project.options), project.created_at, project.updated_at),
        )
        self.conn.commit()
        self.log_activity(project.project_id, f"Created study pack '{project.name}'")
        return project

    def update_project(self, project: Project) -> None:
        project.updated_at = now_iso()
        self.conn.execute(
            "UPDATE projects SET name=?, subject=?, academic_level=?, options_json=?, updated_at=? WHERE project_id=?",
            (project.name, project.subject, project.academic_level, _j(project.options), project.updated_at, project.project_id),
        )
        self.conn.commit()

    def touch_project(self, project_id: str) -> None:
        self.conn.execute("UPDATE projects SET updated_at=? WHERE project_id=?", (now_iso(), project_id))
        self.conn.commit()

    @staticmethod
    def _project(row) -> Project:
        return Project(project_id=row["project_id"], name=row["name"], subject=row["subject"],
                       academic_level=row["academic_level"], options=json.loads(row["options_json"]),
                       created_at=row["created_at"], updated_at=row["updated_at"])

    def get_project(self, project_id: str) -> Project | None:
        row = self.conn.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        return self._project(row) if row else None

    def list_projects(self) -> list[Project]:
        rows = self.conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [self._project(r) for r in rows]

    def delete_project(self, project_id: str, uploads_dir: Path | None = None, generated_dir: Path | None = None) -> None:
        """Delete a study pack: DB rows (cascades to documents, chunks, topics, resources, tasks, evaluations),
        its activity/stage-run log, uploaded files and exported files."""
        self.conn.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
        self.conn.execute("DELETE FROM activity WHERE project_id=?", (project_id,))
        self.conn.execute("DELETE FROM stage_runs WHERE project_id=?", (project_id,))
        self.conn.commit()
        for base in (uploads_dir, generated_dir):
            if base is not None:
                target = (base / project_id).resolve()
                if base.resolve() in target.parents:  # never delete outside the data folders
                    shutil.rmtree(target, ignore_errors=True)

    # --------------------------------------------------------------- documents
    def add_document(self, doc: Document) -> Document:
        self.conn.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)",
            (doc.document_id, doc.project_id, doc.filename, doc.file_type, doc.storage_path, doc.sha256,
             doc.size_bytes, doc.processing_status, _j(doc.metadata), doc.created_at),
        )
        self.conn.commit()
        return doc

    def find_document_by_hash(self, project_id: str, sha256: str) -> Document | None:
        row = self.conn.execute("SELECT * FROM documents WHERE project_id=? AND sha256=?", (project_id, sha256)).fetchone()
        return self._document(row) if row else None

    @staticmethod
    def _document(row) -> Document:
        return Document(document_id=row["document_id"], project_id=row["project_id"], filename=row["filename"],
                        file_type=row["file_type"], storage_path=row["storage_path"], sha256=row["sha256"],
                        size_bytes=row["size_bytes"], processing_status=row["processing_status"],
                        metadata=json.loads(row["metadata_json"]), created_at=row["created_at"])

    def list_documents(self, project_id: str) -> list[Document]:
        rows = self.conn.execute("SELECT * FROM documents WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
        return [self._document(r) for r in rows]

    def update_document_status(self, document_id: str, status: str, metadata: dict | None = None) -> None:
        if metadata is None:
            self.conn.execute("UPDATE documents SET processing_status=? WHERE document_id=?", (status, document_id))
        else:
            self.conn.execute("UPDATE documents SET processing_status=?, metadata_json=? WHERE document_id=?",
                              (status, _j(metadata), document_id))
        self.conn.commit()

    def delete_document(self, document_id: str) -> None:
        row = self.conn.execute("SELECT storage_path FROM documents WHERE document_id=?", (document_id,)).fetchone()
        self.conn.execute("DELETE FROM documents WHERE document_id=?", (document_id,))
        self.conn.commit()
        if row:
            Path(row["storage_path"]).unlink(missing_ok=True)

    # ------------------------------------------------------------------ chunks
    def replace_chunks(self, document_id: str, chunks: Iterable[ContentChunk]) -> int:
        self.conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
        rows = [(c.chunk_id, c.document_id, c.project_id, c.seq, c.content, c.content_type, c.page_number,
                 c.slide_number, c.heading, c.section_id, c.source_reference, c.extraction_confidence,
                 int(c.needs_review)) for c in chunks]
        self.conn.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def update_chunk_content(self, chunk_id: str, content: str, needs_review: bool, confidence: float) -> None:
        self.conn.execute("UPDATE chunks SET content=?, needs_review=?, extraction_confidence=? WHERE chunk_id=?",
                          (content, int(needs_review), confidence, chunk_id))
        self.conn.commit()

    def list_chunks(self, project_id: str) -> list[ContentChunk]:
        rows = self.conn.execute(
            "SELECT c.*, d.filename FROM chunks c JOIN documents d ON d.document_id=c.document_id "
            "WHERE c.project_id=? ORDER BY d.created_at, c.seq", (project_id,)).fetchall()
        return [ContentChunk(chunk_id=r["chunk_id"], document_id=r["document_id"], project_id=r["project_id"],
                             document_name=r["filename"], seq=r["seq"], content=r["content"],
                             content_type=r["content_type"], page_number=r["page_number"],
                             slide_number=r["slide_number"], heading=r["heading"], section_id=r["section_id"],
                             source_reference=r["source_reference"], extraction_confidence=r["extraction_confidence"],
                             needs_review=bool(r["needs_review"])) for r in rows]

    # ---------------------------------------------------------------- analysis
    def save_analysis(self, project_id: str, analysis: dict | None = None, strategy: dict | None = None) -> None:
        existing = self.get_analysis(project_id)
        analysis = analysis if analysis is not None else existing.get("analysis")
        strategy = strategy if strategy is not None else existing.get("strategy")
        self.conn.execute(
            "INSERT INTO analyses VALUES (?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET "
            "analysis_json=excluded.analysis_json, strategy_json=excluded.strategy_json, updated_at=excluded.updated_at",
            (project_id, _j(analysis) if analysis is not None else None,
             _j(strategy) if strategy is not None else None, now_iso()))
        self.conn.commit()

    def get_analysis(self, project_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM analyses WHERE project_id=?", (project_id,)).fetchone()
        if not row:
            return {}
        return {"analysis": json.loads(row["analysis_json"]) if row["analysis_json"] else None,
                "strategy": json.loads(row["strategy_json"]) if row["strategy_json"] else None}

    # ------------------------------------------------------------------ topics
    def replace_topics(self, project_id: str, topics: list[Topic]) -> None:
        """Replace the topic tree. Resources of removed topics are deleted via cascade."""
        keep = {t.topic_id for t in topics}
        existing = [r["topic_id"] for r in self.conn.execute("SELECT topic_id FROM topics WHERE project_id=?", (project_id,))]
        for topic_id in existing:
            if topic_id not in keep:
                self.conn.execute("DELETE FROM topics WHERE topic_id=?", (topic_id,))
        # Parents first so the FK is satisfied.
        ordered = sorted(topics, key=lambda t: (t.parent_topic_id is not None, t.order_index))
        for t in ordered:
            self.conn.execute(
                "INSERT INTO topics VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(topic_id) DO UPDATE SET "
                "parent_topic_id=excluded.parent_topic_id, title=excluded.title, description=excluded.description, "
                "learning_objectives_json=excluded.learning_objectives_json, prerequisites_json=excluded.prerequisites_json, "
                "source_chunk_ids_json=excluded.source_chunk_ids_json, order_index=excluded.order_index",
                (t.topic_id, project_id, t.parent_topic_id, t.title, t.description, _j(t.learning_objectives),
                 _j(t.prerequisites), _j(t.source_chunk_ids), t.order_index))
        self.conn.commit()

    @staticmethod
    def _topic(row) -> Topic:
        return Topic(topic_id=row["topic_id"], project_id=row["project_id"], parent_topic_id=row["parent_topic_id"],
                     title=row["title"], description=row["description"],
                     learning_objectives=json.loads(row["learning_objectives_json"]),
                     prerequisites=json.loads(row["prerequisites_json"]),
                     source_chunk_ids=json.loads(row["source_chunk_ids_json"]), order_index=row["order_index"])

    def list_topics(self, project_id: str) -> list[Topic]:
        rows = self.conn.execute("SELECT * FROM topics WHERE project_id=? ORDER BY order_index", (project_id,)).fetchall()
        return [self._topic(r) for r in rows]

    def get_topic(self, topic_id: str) -> Topic | None:
        row = self.conn.execute("SELECT * FROM topics WHERE topic_id=?", (topic_id,)).fetchone()
        return self._topic(row) if row else None

    def update_topic(self, topic: Topic) -> None:
        self.replace_topics_partial([topic])

    def replace_topics_partial(self, topics: list[Topic]) -> None:
        for t in topics:
            self.conn.execute(
                "UPDATE topics SET title=?, description=?, learning_objectives_json=?, prerequisites_json=?, "
                "source_chunk_ids_json=?, order_index=?, parent_topic_id=? WHERE topic_id=?",
                (t.title, t.description, _j(t.learning_objectives), _j(t.prerequisites), _j(t.source_chunk_ids),
                 t.order_index, t.parent_topic_id, t.topic_id))
        self.conn.commit()

    # --------------------------------------------------------------- resources
    def save_resource(self, res: Resource) -> Resource:
        """Insert a new version; older versions are kept but marked non-current."""
        row = self.conn.execute(
            "SELECT MAX(version) AS v FROM resources WHERE project_id=? AND resource_type=? AND topic_id IS ?",
            (res.project_id, res.resource_type, res.topic_id)).fetchone()
        res.version = (row["v"] or 0) + 1
        self.conn.execute("UPDATE resources SET is_current=0 WHERE project_id=? AND resource_type=? AND topic_id IS ?",
                          (res.project_id, res.resource_type, res.topic_id))
        self.conn.execute(
            "INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (res.resource_id, res.project_id, res.topic_id, res.resource_type, res.version, 1, _j(res.content),
             res.prompt_id, res.prompt_version, res.provider, res.model, res.origin, res.created_at))
        self.conn.commit()
        return res

    @staticmethod
    def _resource(row) -> Resource:
        return Resource(resource_id=row["resource_id"], project_id=row["project_id"], topic_id=row["topic_id"],
                        resource_type=row["resource_type"], version=row["version"], is_current=bool(row["is_current"]),
                        content=json.loads(row["content_json"]), prompt_id=row["prompt_id"],
                        prompt_version=row["prompt_version"], provider=row["provider"], model=row["model"],
                        origin=row["origin"], created_at=row["created_at"])

    def get_resource(self, project_id: str, topic_id: str | None, resource_type: str) -> Resource | None:
        row = self.conn.execute(
            "SELECT * FROM resources WHERE project_id=? AND topic_id IS ? AND resource_type=? AND is_current=1",
            (project_id, topic_id, resource_type)).fetchone()
        return self._resource(row) if row else None

    def get_resource_by_id(self, resource_id: str) -> Resource | None:
        row = self.conn.execute("SELECT * FROM resources WHERE resource_id=?", (resource_id,)).fetchone()
        return self._resource(row) if row else None

    def list_resources(self, project_id: str, resource_type: str | None = None, current_only: bool = True) -> list[Resource]:
        sql = "SELECT * FROM resources WHERE project_id=?"
        params: list[Any] = [project_id]
        if resource_type:
            sql += " AND resource_type=?"
            params.append(resource_type)
        if current_only:
            sql += " AND is_current=1"
        rows = self.conn.execute(sql + " ORDER BY created_at", params).fetchall()
        return [self._resource(r) for r in rows]

    def resource_versions(self, project_id: str, topic_id: str | None, resource_type: str) -> list[Resource]:
        rows = self.conn.execute(
            "SELECT * FROM resources WHERE project_id=? AND topic_id IS ? AND resource_type=? ORDER BY version DESC",
            (project_id, topic_id, resource_type)).fetchall()
        return [self._resource(r) for r in rows]

    # ------------------------------------------------------------------- tasks
    def upsert_task(self, task: GenerationTask) -> None:
        task.updated_at = now_iso()
        self.conn.execute(
            "INSERT INTO generation_tasks VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(project_id, topic_id, resource_type) "
            "DO UPDATE SET status=excluded.status, attempts=excluded.attempts, error=excluded.error, updated_at=excluded.updated_at",
            (task.task_id, task.project_id, task.topic_id, task.resource_type, task.status, task.attempts, task.error, task.updated_at))
        self.conn.commit()

    def get_task(self, project_id: str, topic_id: str | None, resource_type: str) -> GenerationTask | None:
        row = self.conn.execute(
            "SELECT * FROM generation_tasks WHERE project_id=? AND topic_id IS ? AND resource_type=?",
            (project_id, topic_id, resource_type)).fetchone()
        return GenerationTask(**dict(row)) if row else None

    def list_tasks(self, project_id: str) -> list[GenerationTask]:
        rows = self.conn.execute("SELECT * FROM generation_tasks WHERE project_id=?", (project_id,)).fetchall()
        return [GenerationTask(**dict(r)) for r in rows]

    def mark_stale_running_tasks(self, project_id: str, older_than_s: int = 1800) -> int:
        """Tasks left 'running' longer than any legitimate run could take become retryable ('interrupted').

        A task that is genuinely in progress (in this app, another browser tab, or the CLI) is
        recent, so it is left alone; the age threshold exceeds provider timeout x repair attempts.
        """
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_s)).isoformat(timespec="seconds")
        cur = self.conn.execute(
            "UPDATE generation_tasks SET status='interrupted', error='Generation was interrupted (page closed or app restarted)' "
            "WHERE project_id=? AND status='running' AND updated_at < ?", (project_id, cutoff))
        self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------- evaluations
    def save_evaluation(self, ev: EvaluationRecord) -> EvaluationRecord:
        self.conn.execute("INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?)",
                          (ev.evaluation_id, ev.project_id, ev.topic_id, ev.resource_id, ev.coverage_score,
                           _j(ev.report), ev.evaluation_status, ev.created_at))
        self.conn.commit()
        return ev

    def list_evaluations(self, project_id: str, topic_id: str | None = None, latest_only: bool = True) -> list[EvaluationRecord]:
        rows = self.conn.execute("SELECT * FROM evaluations WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
        records = [EvaluationRecord(evaluation_id=r["evaluation_id"], project_id=r["project_id"], topic_id=r["topic_id"],
                                    resource_id=r["resource_id"], coverage_score=r["coverage_score"],
                                    report=json.loads(r["report_json"]), evaluation_status=r["evaluation_status"],
                                    created_at=r["created_at"]) for r in rows]
        if topic_id is not None:
            records = [r for r in records if r.topic_id == topic_id]
        if latest_only:
            seen, latest = set(), []
            for r in records:
                if r.topic_id not in seen:
                    seen.add(r.topic_id)
                    latest.append(r)
            records = latest
        return records

    # -------------------------------------------------------------- stage runs
    def save_stage_run(self, run: StageRun) -> None:
        self.conn.execute("INSERT INTO stage_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (run.run_id, run.project_id, run.stage_id, run.prompt_version, run.provider, run.model,
                           run.attempts, int(run.success), run.duration_s, run.prompt_tokens, run.output_tokens,
                           run.error, run.created_at))
        self.conn.commit()

    def list_stage_runs(self, project_id: str, limit: int = 200) -> list[StageRun]:
        rows = self.conn.execute("SELECT * FROM stage_runs WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                                 (project_id, limit)).fetchall()
        return [StageRun(**{**dict(r), "success": bool(r["success"])}) for r in rows]

    # ---------------------------------------------------------------- activity
    def log_activity(self, project_id: str | None, message: str) -> None:
        self.conn.execute("INSERT INTO activity (project_id, message, created_at) VALUES (?,?,?)",
                          (project_id, message, now_iso()))
        self.conn.commit()

    def recent_activity(self, limit: int = 15) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT a.*, p.name AS project_name FROM activity a LEFT JOIN projects p ON p.project_id=a.project_id "
            "ORDER BY a.activity_id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
