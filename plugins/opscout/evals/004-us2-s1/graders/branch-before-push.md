---
type: tool_order
before: {tool: Bash, input_match: '"command": "git (switch -c|checkout -b) '}
after: {tool: Bash, input_match: '"command": "git push'}
---
