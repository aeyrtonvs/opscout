---
fixture: skeptic-spike
arms: plugin
max_turns: 40
allowed_tools:
- Skill
- Agent
- mcp__plugin_opscout_opscout
tags:
- FR-029
---

Should we tune this threshold?

CRITICAL: example-api 5XX errors above threshold
Project: example-api
Environment: Production
Resource: example-api-alb
Account: 123456789012
Region: us-east-1
Metric: HTTPCode_Target_5XX_Count
Threshold: 50
Time: 2026-11-06T11:40:00+00:00
