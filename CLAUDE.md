# CLAUDE.md - DevsContext

## Project Overview

DevsContext is an MCP server that aggregates context from multiple sources (Jira, Fireflies, local docs) to help AI coding assistants understand development tasks better.

## Architecture

```
src/devscontext/
├── server.py       # MCP server entry point, tool definitions
├── core.py         # ContextOrchestrator - coordinates adapters
├── synthesis.py    # Combines/ranks context from multiple sources
├── config.py       # YAML config loader using Pydantic
├── cache.py        # TTL cache wrapper around cachetools
├── cli.py          # CLI entry point
└── adapters/
    ├── base.py     # Abstract Adapter class, ContextData model
    ├── jira.py     # Jira API adapter (stub)
    ├── fireflies.py # Fireflies API adapter (stub)
    └── local_docs.py # Local markdown file adapter (stub)
```

## Key Classes

- `ContextOrchestrator` (core.py): Main coordinator that initializes adapters based on config, fetches context in parallel, and synthesizes results
- `Adapter` (adapters/base.py): Abstract base class for context sources
- `ContextData` (adapters/base.py): Pydantic model for structured context
- `Config` (config.py): Pydantic model for YAML configuration

## Development Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run the MCP server
devscontext serve

# Run tests
pytest

# Type check
mypy src/devscontext

# Lint
ruff check src/
```

## Current Status

Day 1 implementation - stub adapters return hardcoded data. The MCP integration is complete and can be tested end-to-end.

## Next Steps

1. Implement real Jira API calls in `adapters/jira.py`
2. Implement Fireflies API integration
3. Implement actual file search in local_docs adapter
4. Add LLM-based context synthesis
5. Add more sophisticated relevance scoring
