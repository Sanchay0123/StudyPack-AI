# Prompt-Engineering Framework

The prompt engine is the main technical contribution of StudyPack AI. It replaces a single "summarise this" prompt with a
**modular, versioned, multi-stage chain** whose stages are independently testable and provider-independent.

## 1. Components

| Module | Responsibility |
|---|---|
| `prompt_engine/templates/*.md` | Prompt templates (front matter + `## SYSTEM` / `## USER`). Editable without touching code. |
| `prompt_engine/templates/partials/` | Shared blocks: `global_rules` (injection defence, fidelity, provenance, citations, JSON-only), `output_format`. |
| `prompt_engine/templates/fewshot/` | Few-shot material selected at run time (examples by style, question/flashcard style, Mermaid syntax, teaching strategies). |
| `template_loader.py` | Parses templates, expands partials, detects variables, computes a **content fingerprint**. |
| `prompt_builder.py` | Renders variables, adds a human-readable schema outline, attaches the JSON schema, neutralises delimiter-breaking text. |
| `context_manager.py` | Token budgeting, labelled source formatting (`[S1] (doc, p. 3, section …)`), topic chunk selection, batching. |
| `prompt_router.py` | Maps a task to its template and selects few-shot material from the teaching strategy. |
| `stage_runner.py` | Executes one stage: budget check → generate → parse → validate (schema + semantic) → targeted repair → record. |
| `orchestrator.py` | Controls the chain and persistence: analysis (P01–P04), per-topic generation (P05–P10), QA loop (P11–P12). |
| `schemas/` | Pydantic models for every structured output, with validators (quiz answer consistency, Mermaid sanity, …). |

## 2. The chain

```
P01 document_analysis ──► P02 topic_mapping ──► P03 learning_objectives ──► P04 teaching_strategy
                                                                                  │ (strategy JSON)
                    ┌─────────────────────────────────────────────────────────────┘
                    ▼   per topic
             P05 lecture_notes ──► notes digest ──► P06 examples · P07 questions · P08a revision · P08b flashcards
                    │                                P09 diagrams · P10 quizzes
                    ▼
             P11 quality_evaluation (+ deterministic coverage / grounding / consistency checks)
                    │ findings
                    ▼
             P12 refinement (section-level edits) ──► new notes version ──► P11 again (revalidation)
```

Each stage receives **only the context it needs**: P02 sees a compact section index, not the whole document; P05 sees
one topic's source chunks plus the strategy; P06–P10 see the topic's chunks plus a digest of the notes (so resources stay
consistent with the notes); P11 sees the notes, the required subtopics and the evidence.

## 3. Techniques and where they are used

| Technique | Where |
|---|---|
| **Role prompting** | Every template opens with a role: curriculum designer (P01), instructor (P02), educational designer (P03), master teacher (P04), professor (P05), tutor (P06), exam specialist (P07), learning scientist (P08b), visual designer (P09), assessment designer (P10), *independent reviewer who did not write the notes* (P11), revising author (P12). |
| **Contextual prompting** | Subject, level, topic description, subtopics, objectives, prerequisites, strategy and labelled source material are injected per stage. |
| **Zero-shot** | P01, P03, P05, P08a, P10, P11 rely on precise instructions only. |
| **Few-shot** | P04 (illustrative teaching strategies), P06 (example style routed by the strategy: quantitative / programming / conceptual / case study), P07 (question format), P08b (good vs bad flashcards), P09 (valid Mermaid patterns). Examples are generic, not tied to a syllabus. |
| **Prompt chaining** | P01→P02→P03→P04 build the context used by P05–P10; notes feed the other resources; P11 findings feed P12. |
| **Structured output** | Pydantic schema → JSON schema sent to the provider (Ollama grammar-constrained `format`, Gemini `response_json_schema`) **and** a field outline in the prompt so the model knows what fields mean. |
| **Validation + iterative refinement** | `stage_runner` validates schema and semantic rules (e.g. section IDs must exist, quiz answers must be options, Mermaid must parse). On failure it sends the previous output plus the exact errors and asks for a corrected object; it does not restart. |
| **Independent evaluation** | P11 is a separate evaluator persona with temperature 0.1. Its claims are *verified*: a subtopic is "covered" only if the quoted evidence is actually found in the notes. |
| **Targeted refinement** | P12 returns section-level `replace` / `add` / `remove` operations, which are applied to the notes. Previous versions are kept, and the new version is re-evaluated. |
| **Subject adaptation** | P04 produces a structured strategy (section kinds, example style, question and diagram types, notation guidance, pitfalls) that is injected into P05–P10. No subject is hard-coded. |

No stage asks the model to reveal chain-of-thought. Qwen's thinking mode is disabled (`OLLAMA_THINK=false`), and evaluations are
requested as concise structured findings with evidence.

## 4. Prompt-injection defence

1. `global_rules` (in every system prompt) declares everything inside `<source_material>` to be untrusted data and gives explicit
   examples of instructions to ignore.
2. `neutralize_source_text()` rewrites any `</source_material>`, `## SYSTEM` / `## USER` markers and chat-template tokens found in
   uploaded text, so a document cannot close the data block or forge prompt structure.
3. The application never executes or acts on model output beyond validated JSON. Provider configuration and credentials are never
   part of any prompt.
4. The sample `computer_networks_module1.pdf` contains a deliberate injection sentence; see PROJECT_STATUS.md for the observed behaviour.

## 5. Versioning

Each template has a semantic `version` in its front matter. The loader also computes a 7-character **fingerprint** of the fully
expanded text, partials included, so the identifier `P05:lecture_notes@1.1.0+660db3e` changes whenever any part of the effective prompt
changes. Every generated resource and every stage run stores the prompt id and version.

### Changelog
| Template | Version | Change | Reason (observed) |
|---|---|---|---|
| P05 lecture_notes | 1.0.0 → 1.1.0 | Explicit depth targets (≥5 sections, ~900–1600 words, ≥2 paragraphs per concept); thin sources must still be explained using labelled supplementary sections; schema `sections` min 3 → 5. | First live run produced 3 sections / ~180 words for a topic, which is a summary, not standalone notes. |
| P02 topic_mapping | 1.0.0 → 1.1.0 | Subtopics derived from content (listed or explained concepts), not just headings; section index now lists item lead-phrases. | Live run: "LAN Topologies" got no subtopics although bus/ring/star/mesh were listed. |
| partial global_rules | (fingerprint change) | Citations only via `source_labels`; no meta-references ("the source material", "S1") inside text. | Examples contained steps like "Identify the definition from the source material (S1)". |
| P11 quality_evaluation | 1.0.0 → 1.1.0 | Evidence quotes must be copied exactly from the NOTES (8–20 words); every "needs_refinement" verdict must be justified by a listed finding. | Live E2E: the evaluator paraphrased evidence ("establishes, maintains…" vs notes "establishing, maintaining…"), and it often answered "needs_refinement" while listing no problems. |

| P12 refinement | 1.0.0 → 1.1.0 | Lists the sections that have findings and forbids replacing others; "Summary" / "Key terms" are fields, not sections. Enforced in code too: edits to sections without findings are skipped (logged), "Summary"/"Overview" targets update those fields, and a replace+remove of the same section keeps the fix. | Live History pass: P12 rewrote 6 of 7 sections for a topic with few findings, "replaced" the Key terms block, added a duplicate Summary section, and once replaced then removed the same section. |

Related non-prompt changes made for the same observations: evidence matching now tolerates word-form changes within one
local window of the notes (stems), but still rejects quotes about absent content. Topic status is now determined by
**concrete findings only** (missing or partial subtopics, medium or high unsupported claims, factual concerns). P12 receives a
targeted view (only the sections named in findings) when the full notes would overflow the context. This fixed a live
overflow on the TCP/IP topic.

## 6. Adding or changing a prompt
1. Edit the `.md` template (or add one with a new `name`). Bump `version`.
2. If the output shape changes, edit or add the Pydantic schema and register it in `schemas/__init__.py`.
3. Run `pytest tests/test_prompts.py`. It checks that every pipeline template has a role, a task, the injection defence, an output format and fidelity rules.
4. Optionally run `scripts/run_pipeline.py` on a sample and compare outputs and QA reports.
