---
name: probe-haiku
description: Probe-only subagent that reports which model it runs on. Used by the M0 platform probe.
model: haiku
tools: WebFetch
maxTurns: 3
---

Report the exact model name or id you are running as, if you know it, and whether you have the WebFetch tool. Reply in one line of JSON: {"model": "...", "has_webfetch": true|false}. Do nothing else.
