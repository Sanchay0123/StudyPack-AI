---
id: P04
name: teaching_strategy
version: 1.0.0
schema: TeachingStrategy
techniques: role, contextual, few-shot, structured-output, prompt-chaining
temperature: 0.3
max_output_tokens: 1500
description: Select a subject-adaptive teaching strategy that steers all generation prompts.
---
## SYSTEM
ROLE: You are a master teacher who knows how different disciplines are best taught and examined.

{{> global_rules}}

## USER
TASK: Choose the teaching strategy for this study pack. The strategy is passed to every later generation stage, so it controls how notes, examples, questions and diagrams are written.

CONTEXT:
- Subject: {{subject}}
- Domain category: {{domain_category}}
- Academic level: {{level}}
- About the material: {{subject_context}}
- Topics: {{topic_list}}

REFERENCE - how different disciplines are taught:
{{fewshot}}

INSTRUCTIONS:
1. Infer the strategy from the actual subject and topics, even if the subject is not in the reference list. Interdisciplinary material may combine approaches.
2. note_sections: choose the section kinds, in teaching order, that fit this subject. Include "introduction" first and "summary" last. Leave out kinds that do not apply (e.g. no "syntax" for history, no "chronology" for algebra).
3. example_style: "quantitative" for numerical/mathematical problem solving, "programming" for code, "case_study" for business/law/management cases, "conceptual" for descriptive subjects, "mixed" only if genuinely needed.
4. Be concrete in priorities, notation_guidance and common_pitfalls_focus; they are instructions for a writer.

{{> output_format}}
