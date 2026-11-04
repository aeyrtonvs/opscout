---
max_turns: 4
allowed_tools: [Skill]
tags: ["FR-019"]
---

Here is what we did today. The example-api service on example-prod returned 504 errors from 09:00. We first suspected the cache layer (example-cache) and then DNS (EXAMPLE-DNS-RESOLVER); both checked out fine, so we moved on. The cause was the upstream timeout of 5 s, too short for the report endpoint. We raised it to 30 s at 10:15 and the 504s stopped. Still to do: add an alert on the endpoint's latency.

Write the team chat message and post it to #alerts-example.
