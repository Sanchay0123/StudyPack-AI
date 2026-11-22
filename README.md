# StudyPack AI

Turn lecture PDFs, slide decks, Word documents and notes into a complete, **source-grounded study pack**:

- comprehensive lecture notes, with every section labelled *from source*, *supplementary* or *inferred*, and traced back to pages and slides
- worked examples
- suggested important questions
- quick revision notes
- flashcards
- diagrams and flowcharts (Mermaid)
- interactive practice quizzes
- an independent quality report (evidence-verified coverage, grounding, consistency, unsupported claims) with targeted refinement

It runs fully locally on a 6 GB GPU with Ollama + Qwen3.5 4B. Gemini can be added as the primary provider, with Ollama as the fallback.
The core of the project is a **modular, subject-adaptive, multi-stage prompt-engineering framework**: see
[docs/PROMPT_ENGINEERING.md](docs/PROMPT_ENGINEERING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 1. Installation (Windows, everything inside this folder)

Requirements: Python 3.11+ and an NVIDIA GPU (optional; the CPU works, but slowly). Everything else is installed **inside the project folder**.
Deleting the folder removes the app, its virtualenv, Ollama and the model weights.

```powershell
# 1. Python environment (creates .venv\ in the project)
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. Portable Ollama + model (downloads ~1.6 GB Ollama + ~3.3 GB model into tools\ollama\)
powershell -ExecutionPolicy Bypass -File scripts\setup_ollama.ps1

# 3. (optional) configuration
copy .env.example .env
```

`setup_ollama.ps1` downloads the official Ollama Windows zip (v0.40.17), extracts it to `tools\ollama\`, starts it with
`OLLAMA_MODELS=tools\ollama\models`, and pulls `qwen3.5:4b-q4_K_M`. No system-wide installation or registry changes are made.

## 2. Running

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_app.ps1
```
This starts the local Ollama server (if it isn't already running) and opens the app at http://localhost:8501.
Stop Ollama and free GPU memory with `scripts\stop_ollama.ps1`. Link directly to a pack with `http://localhost:8501/notes?project=<project id>`.

**Typical workflow:** Create Study Pack (upload files) → Document Analysis (check and edit the detected subject, topic map and strategy; optionally describe figures with the vision model) →
Generation Center (runs as a background job: you can read finished notes meanwhile; progress is saved per item; failures can be retried) → Lecture Notes / Revision Center / Quiz Center →
Quality Report (evaluate, then refine) → Export (Markdown or PDF). Notes can be edited by hand in the notes viewer (saved as a new version, marked "edited by you"); study packs can be deleted from the dashboard.

Headless alternative (same database, so results open in the UI):
```powershell
.venv\Scripts\python scripts\run_pipeline.py --name "My course" lecture1.pdf slides.pptx --resources all --evaluate --refine --export
```

## 3. Model setup

| Setting | Default | Notes |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3.5:4b-q4_K_M` | Verified on ollama.com (3.3 GB). Any Ollama model works; change it in `.env`. |
| `OLLAMA_THINK` | `false` | Qwen3.5 "thinking" mode. Disabled: it spends output tokens on hidden reasoning and slows generation. |
| `DEFAULT_CONTEXT_LENGTH` | `8192` | Measured: the model plus an 8K cache fits fully in 6 GB VRAM (3.36 GB). |
| `MAX_OUTPUT_TOKENS` | `3072` | Per stage. Templates may request less. |

Measured on an RTX 3050 6 GB laptop: about 42 tokens/s warm. The first request after starting takes longer while the model loads. The analysis
chain (P01–P04) takes about 70 s for a short document. One topic's 7 resources take about 2.5 minutes.

### Gemini (optional)
Set `GEMINI_API_KEY` (and optionally `GEMINI_MODEL`, default `gemini-2.5-flash`) in `.env`, then set `DEFAULT_PROVIDER=gemini` and
`FALLBACK_PROVIDER=ollama`. Without a key, Gemini shows as unavailable and everything runs on Ollama. With a key, Ollama is still used whenever Gemini does not respond within `GEMINI_TIMEOUT_S` (default 120 s), or on network, server, quota or key errors; after such a failure Gemini is skipped for `PROVIDER_COOLDOWN_S` (default 300 s) so requests do not keep waiting on it. Fallback happens only for
availability, network, quota or authentication failures, never to hide invalid output.

### OCR (optional)
Scanned PDF pages are detected automatically. Reading them needs the Tesseract binary, which is **not bundled**.
Install it (e.g. the UB Mannheim Windows build) and set `TESSERACT_CMD=C:\path\to\tesseract.exe`, or place it at
`tools\tesseract\tesseract.exe`. Without it, scanned pages are reported and skipped, never guessed.

## 4. Environment variables

See `.env.example` for the full list with comments: provider routing, Ollama/Gemini settings, generation limits, upload limit
(`MAX_UPLOAD_MB`, default 50), chunk size, OCR, storage paths and log level. Relative paths are resolved against the project root.
Never commit `.env`.

## 5. Testing

```powershell
.venv\Scripts\python -m pytest            # offline suite (no model needed; uses clearly marked test fixtures)
.venv\Scripts\python -m pytest -m live    # calls the real configured model
```
The offline suite covers the extractors (including corrupted, scanned and spoofed files), normalisation, the prompt templates (required
elements, injection neutralisation), the stage runner (repair, retry limits, context overflow), the analysis chain, generation with resume
and retry, evaluation (evidence verification, grounding, consistency), refinement, providers and routing, exports (Markdown, PDF, diagrams),
and every UI page, including an interactive quiz submission.

## 6. Experiments (prompt-engineering evaluation)

```powershell
.venv\Scripts\python experiments\run_experiment.py --project-id <id> [--project-id <id> ...]
.venv\Scripts\python experiments\run_experiment.py --summarize
```
This compares A (baseline prompt), B (single structured prompt) and C (the multi-stage pipeline) on the same material and model.
It records lexical topic coverage, blind LLM-judge rubric scores, unsupported numbers and size. Results are written to `experiments/results/`
(JSON + a CSV template for human 1–5 ratings). Raw outputs go to `experiments/runs/`.

## 7. Project layout
```
app.py                Streamlit entry point          config/        settings, logging, hardware
ingestion/            upload + extractors            analyzer/      P01–P04 helpers, section index
prompt_engine/        templates, builder, context, router, stage runner, orchestrator, schemas
generation/           notes + resource generators    evaluation/    coverage, grounding, consistency, P11, P12
providers/            Ollama, Gemini, router         storage/       SQLite schema + repository
export/               Markdown, PDF, diagram render  ui/            pages and components
experiments/          A/B/C comparison               scripts/       setup, start, pipeline CLI, samples
samples/              test documents (3 domains)     tests/         pytest suite
tools/  data/  generated/  logs/   (runtime, git-ignored)
```

## 8. Known limitations
- A 4B local model is fast enough on 6 GB VRAM but makes mistakes. That is why every output is validated, evaluated independently and labelled
  by provenance. Treat "inferred" content and flagged claims with care.
- Equations: `$...$` LaTeX renders in the app (KaTeX) and as images in the PDF (matplotlib mathtext); LaTeX that mathtext cannot parse (e.g. `align`) stays as monospace text.
- Diagrams: flowcharts, mindmaps and timelines are drawn in the PDF. Other Mermaid types (sequence, class...) are printed as source in the PDF
  but render in the app.
- Figures inside documents are saved and can be described by the vision model (Document Analysis → *Describe figures*). Descriptions are labelled as model-generated and flagged for review; tiny images (icons, logos) are skipped.
- Background generation jobs live in the Streamlit server process: you can browse other pages or close the tab, but stopping the server stops the job. Completed items are always saved and the rest can be resumed.
- The lexical grounding and coverage heuristics are indicators, not proof. The evidence-verified evaluator coverage is the primary metric.

See `PROJECT_STATUS.md` for verified results and open items.
