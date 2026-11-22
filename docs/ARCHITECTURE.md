# Architecture

```
Upload ─► ingestion ─► normalizer ─► analyzer (P01–P04) ─► topic map (editable) ─► generation (P05–P10)
                                                                                     │
                                         export ◄── study pack (SQLite) ◄── QA (P11 + checks) ◄─► refinement (P12)
                                                                  ▲
                                                     Streamlit UI (ui/*)
                    providers/ (Ollama | Gemini) behind ProviderRouter, used only through prompt_engine/stage_runner
```

## Packages

| Package | Contents |
|---|---|
| `config/` | `settings.py` (all configuration from env/.env), `logging_config.py` (rotating log, secret redaction), `hardware.py` (GPU detection). |
| `providers/` | `BaseLLMProvider` interface; `OllamaProvider` (HTTP API, structured outputs, `think` flag, per-request `num_ctx`); `GeminiProvider` (official `google-genai` SDK); `ProviderRouter` (primary/fallback); error hierarchy with `fallback_eligible`. |
| `ingestion/` | Upload validation and safe storage; extractors for PDF (PyMuPDF: font-size headings, lists, monospace code, tables, captions, scanned-page detection, optional OCR), DOCX (styles, numbering, tables, body order), PPTX (titles, bullet levels, tables, speaker notes, alt text), TXT/MD; `normalizer.py` (heading-aware chunking with source references); `pipeline.py`. |
| `analyzer/` | `sections.py` (deterministic section index), `domain_detector.py` (keyword hint only), `document_analyzer.py` (P01), `topic_mapper.py` (P02 with batching, ID validation, attaching unassigned sections), `learning_objectives.py` (P03, P04). |
| `prompt_engine/` | Templates, builder, context manager, router, stage runner, orchestrator, schemas. See PROMPT_ENGINEERING.md. |
| `generation/` | `jobs.py` (one background generation thread at a time, stop support, progress polled by the UI), `topic_context.py` (everything a stage needs for one topic), `notes_generator.py` (P05 with multi-part generation for large topics), `resource_generators.py` (P06–P10), `labels.py` (removes invented citations, records source metadata). |
| `evaluation/` | `coverage_checker.py` (evidence-verified coverage), `grounding_checker.py` (citation and sentence-support checks), `consistency_checker.py` (cross-resource numbers/terms/formulas), `quality_evaluator.py` (P11 + checks → report + status), `refiner.py` (P12 application), `evaluation_metrics.py`. |
| `storage/` | `database.py` (SQLite, WAL, FK, ordered migrations), `models.py`, `repository.py` (all SQL). |
| `export/` | `collect.py`, `markdown_exporter.py`, `pdf_exporter.py` (ReportLab: title page, TOC, page numbers, Unicode fonts), `mermaid_render.py` (flowchart/mindmap/timeline → vector drawing). |
| `ui/` | Streamlit multipage app: dashboard, create, analysis (topic and strategy editor), generation center, notes viewer, revision center (revision notes, flashcards, questions), quiz center, quality report, export, models & settings. |
| `experiments/` | A/B/C comparison runner, blind judge, results JSON + human-rating CSV. |
| `scripts/` | Portable Ollama setup/start/stop, app launcher, headless pipeline runner, sample builder. |

## Data model (SQLite)

`projects` 1─* `documents` 1─* `chunks`; `projects` 1─1 `analyses` (P01 analysis + P04 strategy JSON);
`projects` 1─* `topics` (self-referencing `parent_topic_id`; `source_chunk_ids` keep traceability);
`topics` 1─* `resources` (`resource_type`, `version`, `is_current`, `origin` generated|refined, prompt id and version, provider, model);
`generation_tasks` (one row per topic × resource; status pending|running|done|failed|interrupted; used for resume and retry);
`evaluations` (full report JSON, coverage score, status); `stage_runs` (every LLM stage: prompt version, attempts, tokens, errors);
`activity`. Foreign keys cascade on delete. The schema is created and upgraded by ordered migrations recorded in `schema_version`.

## Architecture decision records

**ADR-001: Streamlit + SQLite, no extra infrastructure.** The project prioritises AI workflows. Streamlit gives a usable multipage
UI quickly, and SQLite needs no server. Rejected: separate REST backend and SPA (more code, no benefit for a single local user).

**ADR-002: Ollama with `qwen3.5:4b-q4_K_M` as the local default, verified rather than assumed.** The tag was checked on ollama.com
(3.3 GB, 256K context, "thinking" capability). Measured on the target RTX 3050 6 GB: the model is fully GPU-resident (3.36 GB at 8K context)
and runs at about 42 tokens/s warm. Thinking is disabled by default because, with it enabled, a 300-token budget was entirely spent on hidden reasoning.
Ollama is installed **portably inside the project** (`tools/ollama`, `OLLAMA_MODELS=tools/ollama/models`) so the whole system can be removed by deleting one folder.

**ADR-003: Structural retrieval instead of a vector database.** Topics carry the chunk ids of the sections the topic map assigned
to them, so retrieval is a lookup plus budget-aware trimming by keyword relevance. Keyword retrieval is the fallback for topics a student adds by hand.
A vector store would add dependencies without a demonstrated need at study-pack scale. Large topics are handled by multi-part generation, not by silent truncation.

**ADR-004: Grammar-constrained JSON + Pydantic + semantic validators + targeted repair.** Ollama structured outputs guarantee
syntactically valid JSON. Pydantic and custom validators catch semantic errors, such as quiz answers that are not options, unknown section IDs,
or invalid Mermaid. Repairs resend the previous output with precise errors. Validation failures never trigger provider fallback (ADR-005).

**ADR-005: Provider fallback only for availability failures.** `fallback_eligible` is true for unavailable, timeout, quota, auth and
model-not-found errors, and false for malformed responses and context overflow. This prevents a provider switch from masking prompt or
schema bugs.

**ADR-006: Evidence-verified coverage.** An LLM saying "covered" is not enough. The quoted evidence must be found in the notes, otherwise the
subtopic is downgraded to "partial". If the evaluator fails, no coverage score is shown. Lexical "term coverage" is reported separately and is
labelled as a heuristic.

**ADR-007: Section-level refinement with versioning.** P12 emits edit operations rather than a full rewrite. This is cheaper on a small GPU and
preserves good sections. Every refinement creates a new resource version, and old versions stay viewable.

**ADR-008: Per-request context length.** `GenerationRequest.context_length` lets a stage use a larger window (the experiment judge
uses 16K) without changing the global default (8K) tuned for 6 GB VRAM.

## Reliability and security
- Uploads: extension allow-list, magic-byte checks (PDF header, OOXML zip, NUL check for text), size limit, sanitised names. Files are stored under
  generated ids inside `data/uploads/<project>/`, with a path-traversal guard. Uploaded content is never executed.
- Corrupted, encrypted or empty files fail individually with clear messages. One bad file never aborts a batch.
- Generation runs as a server-side background job (one at a time, matching sequential local inference); the UI polls its progress.
- Each generation task is persisted on completion. Tasks left `running` by a closed page are marked `interrupted` and can be retried.
- Secrets come only from environment variables, are never stored in the DB, and are redacted from logs.
