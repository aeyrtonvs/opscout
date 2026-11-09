---
fixture: real-deploy
arms: plugin
max_turns: 40
allowed_tools:
- Skill
- Agent
- mcp__plugin_opscout_opscout
tags:
- FR-004
---

Is this alert real?

CRITICAL: example-api 5XX errors above threshold
Project: example-api
Environment: Staging
Resource: example-api-alb
Account: 000000000000
Region: us-east-1
Metric: HTTPCode_Target_5XX_Count
Threshold: 50
Time: 2026-11-06T11:45:00+00:00
