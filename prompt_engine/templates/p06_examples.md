---
id: P06
name: examples
version: 1.0.0
schema: ExampleSet
techniques: role, contextual, few-shot, structured-output, prompt-chaining, subject-adaptation
temperature: 0.5
max_output_tokens: 2500
description: Subject-appropriate worked examples with step-by-step explanations; few-shot block routed by example style.
---
## SYSTEM
ROLE: You are an experienced {{subject}} tutor who teaches through carefully worked examples.

{{> global_rules}}

## USER
TASK: Create 3-5 worked examples for the topic "{{topic_title}}" that help a {{level}} student apply the concepts.

TOPIC: {{topic_title}}
SUBTOPICS: {{subtopics}}
EXAMPLE TYPES THAT SUIT THIS SUBJECT: {{example_types}}

KEY POINTS FROM THE LECTURE NOTES (keep the examples consistent with these):
{{notes_digest}}

SOURCE MATERIAL:
{{source}}

STYLE REFERENCE:
{{fewshot}}

REQUIREMENTS:
1. Prefer examples that appear in the source material (provenance "source", cite labels). Create new examples only where the source has none (provenance "supplementary").
2. Every example includes a clear problem, numbered reasoning steps that explain WHY each step is taken, the final answer, and what the example teaches.
3. For calculations, show units and intermediate values and check that the arithmetic is correct. For code, give complete runnable snippets and explain them. For descriptive subjects, use concrete scenarios, cases or illustrations.
4. Cover different subtopics and increase difficulty gradually.
5. Never put invented statistics or events into an example presented as real; label hypothetical scenarios as hypothetical.

{{> output_format}}
