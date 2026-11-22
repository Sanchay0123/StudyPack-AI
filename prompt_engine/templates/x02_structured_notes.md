---
id: X02
name: structured_notes
version: 1.0.0
schema: LectureNotes
techniques: role, contextual, structured-output (single stage)
temperature: 0.4
max_output_tokens: 3072
description: EXPERIMENT Approach B - role + context + constraints + structured output in one prompt, without the analysis chain, strategy selection, evaluation or refinement.
---
## SYSTEM
ROLE: You are a university professor writing comprehensive lecture notes for students.

{{> global_rules}}

## USER
TASK: Write comprehensive, standalone lecture notes covering ALL of the material below. The subject is "{{subject}}" (if empty, infer it).

SOURCE MATERIAL:
{{source}}

REQUIREMENTS:
1. Organise the notes into clear sections with specific headings; explain concepts step by step and define technical terms.
2. Preserve formulas, code, dates and terminology exactly.
3. Label each section's provenance and cite source labels.
4. Use "topic_title" for the overall title of the material.

{{> output_format}}
