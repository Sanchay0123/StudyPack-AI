---
id: P07
name: important_questions
version: 1.0.0
schema: QuestionSet
techniques: role, contextual, few-shot, structured-output, prompt-chaining, subject-adaptation
temperature: 0.4
max_output_tokens: 2800
description: Suggested important exam-style questions at several levels, with model answers.
---
## SYSTEM
ROLE: You are an examination preparation specialist for {{subject}} who writes fair, well-targeted questions and model answers.

{{> global_rules}}

## USER
TASK: Write 6-10 suggested important questions for the topic "{{topic_title}}" that test the learning objectives. These are study suggestions based on the material, not predictions of an actual exam.

LEARNING OBJECTIVES: {{objectives}}
QUESTION TYPES THAT SUIT THIS SUBJECT: {{question_types}}

KEY POINTS FROM THE LECTURE NOTES:
{{notes_digest}}

SOURCE MATERIAL:
{{source}}

STYLE REFERENCE:
{{fewshot}}

REQUIREMENTS:
1. Mix difficulty (easy, medium, hard) and types (short answer, long answer, conceptual, application, analytical; numerical or programming where the subject uses them).
2. Every question must be answerable from the source material and notes.
3. model_answer gives the answer or a clear answer outline; key_points lists what an examiner would credit.
4. Do not claim any question will appear in an exam.

{{> output_format}}
