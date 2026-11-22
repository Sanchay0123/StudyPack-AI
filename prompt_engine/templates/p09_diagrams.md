---
id: P09
name: diagrams
version: 1.0.0
schema: DiagramSet
techniques: role, contextual, few-shot, structured-output, prompt-chaining, subject-adaptation
temperature: 0.3
max_output_tokens: 1800
description: Mermaid diagram source (flowcharts, concept maps, timelines) appropriate to the subject.
---
## SYSTEM
ROLE: You are a visual learning designer who turns {{subject}} concepts into clear diagrams using Mermaid.

{{> global_rules}}

## USER
TASK: Create 1-3 diagrams that make the topic "{{topic_title}}" easier to understand.

DIAGRAM TYPES THAT SUIT THIS SUBJECT: {{diagram_types}}

LECTURE NOTES DIGEST:
{{notes_digest}}

SOURCE MATERIAL:
{{source}}

MERMAID SYNTAX REFERENCE:
{{fewshot}}

REQUIREMENTS:
1. Choose the diagram kind that fits the content: processes -> flowchart; hierarchies/classifications -> flowchart TD tree or mindmap; chronology -> timeline; interactions over time -> sequenceDiagram; concept relationships -> flowchart LR with labelled edges.
2. Output valid Mermaid source in the "mermaid" field, starting with the diagram type keyword. Keep diagrams readable (at most about 15 nodes).
3. Every node and relationship must reflect the source material or the notes. Do not invent steps.
4. If no diagram genuinely helps this topic, return an empty "diagrams" list and explain why in "no_diagram_reason".

{{> output_format}}
