# Dashboard v1.0 Release

Updated: 2026-04-07

## Release Status

`Research Control Plane v1.0` is ready for use. Configure your theme in `web_dashboard/dashboard_config.json`.

This release is intentionally scoped. It provides a stable monitoring and reading surface for:

- theme-level visibility
- project-level workspace inspection
- paper-level grouped reading
- card-level content review

It is not positioned as the full future research operating system UI.

## What v1.0 Includes

### Theme Layer

- configurable theme overview (set in `dashboard_config.json`)
- summary metrics
- project health and stage view
- risk alerts with suggested actions
- 7-day trend strip
- activity feed

### Project Layer

- configurable project workspaces (set in `dashboard_config.json`)
- project monitor cards
- blocker and next-step visibility
- document inventory with timestamps
- in-dashboard document preview

### Paper Layer

- project-scoped paper console
- grouped literature buckets
- text search
- card-state filter
- group quick filter

### Card Layer

- metadata view
- summary / method / results / limitations
- evidence snippets
- artifact links
- raw JSON fallback

## Runtime Notes

Recommended startup:

```bash
cd ~/code/research-harness
python3 -m venv .venv
./.venv/bin/pip install -r web_dashboard/requirements.txt
./.venv/bin/python web_dashboard/app.py
```

Open:

```text
http://127.0.0.1:18080
```

## Verification Summary

The following checks were completed during release preparation:

- dashboard route tests passing: `5 passed`
- theme overview endpoint verified
- project detail endpoints verified
- project document preview endpoints verified
- grouped paper endpoint verified
- paper card endpoint verified

## Boundaries After Release

Anything required to keep the current dashboard working and readable belongs to maintenance.

The following should be treated as post-v1 work:

- richer charts
- writable dashboard actions
- experiment management UI
- claim / evidence UI
- manuscript workspace UI
- generalized multi-theme admin UI

## Suggested v1.1 Backlog

- markdown preview improvements for more complex tables and formatting
- richer activity feed prioritization
- project-specific ranking refinement inside paper groups
- topic / project agenda panel that merges risks, next steps, and recent changes
