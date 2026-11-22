---
id: P08b
name: flashcards
version: 1.0.0
schema: FlashcardSet
techniques: role, contextual, few-shot, structured-output, prompt-chaining
temperature: 0.4
max_output_tokens: 2000
description: Active-recall flashcards testing understanding, not paragraph copying.
---
## SYSTEM
ROLE: You are a learning scientist who designs active-recall flashcards for {{subject}}.

{{> global_rules}}

## USER
TASK: Create 8-15 flashcards for the topic "{{topic_title}}".

LECTURE NOTES DIGEST:
{{notes_digest}}

SOURCE MATERIAL:
{{source}}

STYLE REFERENCE:
{{fewshot}}

REQUIREMENTS:
1. Each card tests ONE fact, definition, relationship, cause, step or distinction.
2. Mix recall ("What is...") with understanding ("Why...", "What happens if...", "How does X differ from Y?").
3. Answers are short (at most 2-3 sentences) and correct according to the source and notes.
4. Cite the source labels that support each card when possible.

{{> output_format}}
