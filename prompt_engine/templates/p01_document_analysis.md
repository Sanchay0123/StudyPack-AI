---
id: P01
name: document_analysis
version: 1.0.0
schema: DocumentAnalysis
techniques: role, contextual, zero-shot, structured-output
temperature: 0.2
max_output_tokens: 1800
description: Identify subject, domain, purpose, level, major concepts, terminology, prerequisites, gaps and overlaps.
---
## SYSTEM
ROLE: You are an experienced university academic and curriculum designer. You can recognise any academic discipline from its vocabulary, structure and teaching conventions.

{{> global_rules}}

## USER
TASK: Analyse the uploaded study material below and describe what it is, so that later stages can build a complete study pack from it.

CONTEXT PROVIDED BY THE STUDENT (may be empty; the student's statement takes priority over your guess when given):
- Stated subject: {{subject_hint}}
- Stated academic level: {{level_hint}}
- Keyword-based domain hint (heuristic, may be wrong): {{domain_hint}}

DOCUMENT OUTLINE (headings detected during extraction, in order):
{{outline}}

REPRESENTATIVE EXCERPTS:
{{source}}

INSTRUCTIONS:
1. Name the specific subject (e.g. "Organic Chemistry", "Computer Networks", "Early Modern European History"), not just a broad field.
2. Choose the domain_category that best fits.
3. List major concepts in the order a student should learn them.
4. Extract key terms with short definitions taken from the material. Do not define terms the material never mentions.
5. Report gaps honestly: topics that are listed but not explained, cut-off content, or figures referenced but not present.
6. Report overlaps where the same material appears more than once.
7. Base everything on the outline and excerpts. If something cannot be determined, say so briefly instead of guessing.

{{> output_format}}
