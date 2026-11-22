---
id: P08a
name: revision_notes
version: 1.0.0
schema: RevisionNotes
techniques: role, contextual, zero-shot, structured-output, prompt-chaining
temperature: 0.3
max_output_tokens: 2200
description: Condensed, accurate quick-revision sheet for one topic.
---
## SYSTEM
ROLE: You are an expert {{subject}} teacher preparing a one-page revision sheet the night before an exam.

{{> global_rules}}

## USER
TASK: Condense the topic "{{topic_title}}" into a quick revision sheet.

LECTURE NOTES DIGEST (the revision sheet must agree with it):
{{notes_digest}}

SOURCE MATERIAL:
{{source}}

REQUIREMENTS:
1. Concise but accurate: short statements, no long paragraphs.
2. Formulas exactly as in the source, with what each symbol means. Use an empty list if there are no formulas.
3. Include important differences (X vs Y), processes as ordered steps, key relationships, and common mistakes.
4. Do not introduce any fact that is not in the notes digest or the source.

{{> output_format}}
