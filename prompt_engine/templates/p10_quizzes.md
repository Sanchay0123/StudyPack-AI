---
id: P10
name: quizzes
version: 1.0.0
schema: Quiz
techniques: role, contextual, zero-shot, structured-output, prompt-chaining
temperature: 0.4
max_output_tokens: 2800
description: Practice quiz with mixed question types, correct answers and explanations.
---
## SYSTEM
ROLE: You are an assessment designer who writes fair, unambiguous practice quizzes for {{subject}}.

{{> global_rules}}

## USER
TASK: Create a practice quiz of 6-10 questions for the topic "{{topic_title}}" ({{level}}).

LEARNING OBJECTIVES: {{objectives}}

LECTURE NOTES DIGEST:
{{notes_digest}}

SOURCE MATERIAL:
{{source}}

REQUIREMENTS:
1. Mix types: mostly "mcq" (exactly one correct option, 4 options), plus at least one "multi_select" (2 or more correct options, 4-5 options), one "true_false", and one "short_answer" or "application".
2. correct_answers must be copied EXACTLY from options. For true_false, options are ["True", "False"]. For short_answer/application, options is [] and correct_answers holds a concise model answer.
3. Distractors must be plausible but clearly wrong according to the source. Avoid "all of the above" and trick wording.
4. explanation states why the correct answer is right and why the main distractors are wrong.
5. Every question must be answerable from the source material and notes.

{{> output_format}}
