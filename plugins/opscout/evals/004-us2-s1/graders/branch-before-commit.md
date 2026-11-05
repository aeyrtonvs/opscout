---
type: tool_order
before: {tool: Bash, input_match: '"command": "git (switch -c|checkout -b) (feat|fix|chore|refactor)/[a-z0-9-]+'}
after: {tool: Bash, input_match: '"command": "git commit'}
---
