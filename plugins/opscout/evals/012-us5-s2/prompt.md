---
fixture: monitor-unsupported
arms: plugin
max_turns: 40
allowed_tools:
- Skill
- Agent
- mcp__plugin_opscout_opscout
- mcp__observability
tags:
- FR-016
- FR-018
mcp_config: observability.mcp.json
---

Is this real?

Triggered: [example-api][Production] 5XX errors above 50 on example-api-alb
Time: 2026-11-06T11:45:00+00:00
