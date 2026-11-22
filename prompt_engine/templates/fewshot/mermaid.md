Valid Mermaid patterns (syntax illustration only):

flowchart TD
    A["Start"] --> B{"Condition met?"}
    B -->|Yes| C["Process step"]
    B -->|No| D["Alternative step"]

timeline
    title Major events
    1765 : Event one
    1789 : Event two

mindmap
  root((Central idea))
    Branch A
      Detail A1
    Branch B

Rules: one statement per line; node IDs are single words (A, B, step1); put labels containing spaces, parentheses or punctuation inside double quotes; no HTML; no semicolons inside labels; every opened bracket is closed.
