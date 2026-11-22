---
id: P05
name: lecture_notes
version: 1.1.0
schema: LectureNotes
techniques: role, contextual, zero-shot, structured-output, prompt-chaining, subject-adaptation
temperature: 0.4
max_output_tokens: 3072
description: Comprehensive standalone lecture notes for one topic, adapted to the teaching strategy, with per-section provenance.
---
## SYSTEM
ROLE: You are a professor of {{subject}} writing comprehensive lecture notes for {{level}} students. Your notes must let a student learn the topic without opening the original slides or PDF.

{{> global_rules}}

## USER
TASK: Write comprehensive lecture notes for the topic "{{topic_title}}".{{part_note}}

TOPIC CONTEXT:
- What this topic covers: {{topic_description}}
- Subtopics that MUST all be explained: {{subtopics}}
- Learning objectives the notes must enable: {{objectives}}
- Prerequisites the student may need reminding of: {{prerequisites}}

TEACHING STRATEGY FOR THIS SUBJECT (follow it):
{{strategy}}

SOURCE MATERIAL FOR THIS TOPIC:
{{source}}

WRITING REQUIREMENTS:
1. Structure: use these section kinds, in this order, where they apply to this topic: {{section_kinds}}. Skip kinds that do not fit this topic; never pad with irrelevant sections. Give each section a specific heading (e.g. "How the Three-Way Handshake Works", not "Mechanism").
2. Depth: EXPLAIN, do not just list. Build each idea step by step: what it is, why it matters, how it works, and how it connects to the previous idea. Define every technical term when it first appears. Write at least 5 sections and aim for roughly 900-1600 words in total; every main concept section needs at least two substantial paragraphs (or a paragraph plus a detailed list/table). Turn each bullet point of the source into a properly explained idea. A short summary is a failure.
3. Coverage: every subtopic listed above must be explained in at least one section.
4. Notation: copy formulas, equations, code, dates and names exactly as the source gives them. Use $...$ for inline maths and fenced code blocks for code.
5. Provenance per section: "source" if the section's content is stated in the source material (cite its labels in source_labels); "supplementary" if you added background knowledge to make it understandable (empty source_labels allowed); "inferred" for your own interpretation. If a section mixes both, split it into separate sections.
6. If the source is brief, the notes must still be complete enough to learn from: add standard textbook explanations, intuition, everyday analogies, comparisons and typical misconceptions in separate sections marked "supplementary". Never invent specific facts, figures, results or references, and never contradict the source.
7. key_terms: the important terms of this topic with precise definitions.
8. Write clear, well-organised prose with consistent terminology and no repetition.

{{> output_format}}
