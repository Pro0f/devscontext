# DevsContext

## What is this?
DevsContext is an open-source MCP server (Python) that provides AI coding agents
with synthesized engineering context from SDLC tools (Jira, Fireflies, local docs).

When a developer asks their AI agent to work on a task, DevsContext fetches relevant
data on-demand from connected sources, synthesizes it via LLM into a structured
context block, and returns it through MCP.

## Architecture
- MCP server using the official Python MCP SDK (`mcp` package)
- On-demand fetching: no background processes, no vector DB, no daemons
- Flow: MCP tool call -> fetch from APIs in parallel -> LLM synthesis -> return
- Sources: Jira REST API, Fireflies GraphQL API, local markdown docs
- Synthesis: LLM (Claude Haiku / GPT-4o-mini / Ollama) combines raw data into structured block
- Cache: simple in-memory TTL cache, no persistent storage

## Tech Stack
- Python 3.11+
- `mcp` - MCP Python SDK for server implementation
- `httpx` - async HTTP client for API calls
- `click` - CLI framework
- `pyyaml` - config parsing
- `anthropic` / `openai` - LLM clients for synthesis (optional deps)

## Code Style
- Use async/await for all I/O operations
- Type hints on all function signatures
- Pydantic models for data structures (adapters return typed models, not dicts)
- Follow standard Python conventions (PEP 8, snake_case)
- Keep functions small and focused
- Error handling: never crash the MCP server - catch exceptions in adapters,
  return partial context if a source fails
- Logging: use `logging` module, structured log messages

## Project Structure
- `src/devscontext/server.py` - MCP server setup and tool registration
- `src/devscontext/core.py` - main orchestration (fetch -> extract -> synthesize -> return)
- `src/devscontext/adapters/` - one file per source (jira.py, fireflies.py, local_docs.py)
- `src/devscontext/adapters/base.py` - abstract base class for adapters
- `src/devscontext/synthesis.py` - LLM synthesis prompt and client
- `src/devscontext/cache.py` - in-memory TTL cache
- `src/devscontext/config.py` - YAML config loading and validation
- `src/devscontext/cli.py` - CLI commands (init, test, serve)

## MCP Tools (3 total)
1. `get_task_context(task_id: str)` - full synthesized context for a Jira ticket
2. `search_context(query: str)` - search across all sources by keyword
3. `get_standards(area: str | None)` - coding standards, optionally filtered

## Key Design Decisions
- On-demand fetching, NOT background ingestion
- No vector DB - use API search + keyword matching on local files
- LLM synthesis happens at retrieval time with fresh data
- Config via `.devscontext.yaml` in project root
- Auth credentials via environment variables only (never in config file)
- Graceful degradation: if Fireflies is not configured, skip it and return Jira + docs only

## Testing
- Use pytest with pytest-asyncio
- Mock external APIs in tests (httpx mock)
- Test the synthesis prompt with fixture data

## Commands
- `devscontext init` - create .devscontext.yaml interactively
- `devscontext test` - fetch a sample ticket and show synthesized output
- `devscontext serve` - start MCP server (stdio transport)
