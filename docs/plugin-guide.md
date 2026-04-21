# Plugin Development Guide

## Overview

Research Harness supports five extension points:

| Extension Point | What It Adds |
|----------------|-------------|
| `primitives` | New research operations (paper sources, analysis tools) |
| `gates` | Custom quality checks at stage boundaries |
| `stages` | New orchestrator pipeline steps |
| `advisory_rules` | Heuristic warnings |
| `backends` | Execution providers (LLM, local, remote) |

## Creating a Plugin

### 1. Create plugin directory

```
my-plugin/
├── plugin.yaml      # Plugin manifest
├── my_plugin/
│   ├── __init__.py
│   └── search.py    # Your implementation
└── tests/
    └── test_search.py
```

### 2. Write the manifest

```yaml
name: my-paper-source
version: 0.1.0
description: Custom paper source integration
author: Your Name
license: Apache-2.0
schema_version: 1
min_harness_version: 0.1.0
extension_points:
  primitives:
    - name: my_search
      category: RETRIEVAL
      module: my_plugin.search
      function: search_impl
      requires_llm: false
```

### 3. Implement the primitive

```python
# my_plugin/search.py
from research_harness.primitives.types import PrimitiveResult

def search_impl(*, query: str, max_results: int = 10, **kwargs):
    # Your implementation here
    results = do_search(query, max_results)
    return {"papers": results, "total": len(results)}
```

### 4. Register the plugin

```python
from research_harness.plugin.manager import PluginManager
from pathlib import Path

manager = PluginManager()
plugins = manager.discover([Path("./my-plugin")])
for plugin in plugins:
    manager.register(plugin)
```

## Free vs Premium Boundary

| Free (Apache-2.0) | Premium (Enterprise) |
|---|---|
| All core primitives | Hosted team workspace |
| Local orchestrator | Multi-user collaboration |
| SQLite storage | SSO/SAML/RBAC |
| Plugin development | Managed cloud runs |
| Local observation | Shared skill evolution |
| CLI + MCP server | Web dashboard |
