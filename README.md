# Design Arsenal

A curated, fact-checked library of web-design resources for building **portfolio websites**, plus a weekly Claude agent that scouts for new resources and queues them for human approval in a Google Sheet.

> **Status: under construction (M0 platform probe).** Setup docs will be added before the template release.

- **Library:** `data/resources/`, one JSON record per resource (purpose, pricing with sources, license and client use, portfolio fit, AI-agent access, caveats). The contract lives in `schema/record.schema.json`.
- **Scout:** a scheduled Claude Code cloud routine. It discovers candidates, dedupes them, researches and fact-checks them, and proposes them into `data/inbox/`. A GitHub Action merges its pull request only if the run changed nothing but data.
- **Sheet:** a Google Sheet mirrors the repo. Approve, reject or snooze candidates from your phone.

## Licenses
- Code: MIT (`LICENSE`)
- Data (`data/`, `config/taxonomy.json`, `config/gaps.json`): CC BY 4.0 (`LICENSE-DATA`)
