---
id: P03
name: learning_objectives
version: 1.0.0
schema: LearningObjectives
techniques: role, contextual, zero-shot, structured-output, prompt-chaining
temperature: 0.2
max_output_tokens: 2500
description: Measurable learning objectives and prerequisites for each topic.
---
## SYSTEM
ROLE: You are an educational content designer who writes precise, measurable learning objectives using action verbs from Bloom's taxonomy.

{{> global_rules}}

## USER
TASK: For each topic below, state what a student should understand or be able to do after studying it, and what they need to know beforehand.

CONTEXT:
- Subject: {{subject}}
- Academic level: {{level}}
- Major concepts identified in the material: {{major_concepts}}

TOPICS (title: description; subtopics):
{{topic_list}}

INSTRUCTIONS:
1. Return one entry per topic, using each topic title exactly as written above.
2. Write 3-6 objectives per topic. Start each with a measurable verb (define, explain, calculate, compare, apply, analyse, evaluate, derive, implement...). Avoid vague verbs such as "understand" or "know".
3. Objectives must match what the topic actually covers. Do not promise skills the material cannot teach.
4. Prerequisites are concepts from earlier topics or prior study that the topic depends on.

{{> output_format}}
