**IMPORTANT: DevsContext is the product we are building. The payments-service, PROJ-1234, webhook examples, and other sample data in docs/example/ and tests/fixtures/ are SAMPLE DATA for testing — do NOT implement them. We are building the MCP server tool, not the example application.**

# DevsContext

## What is this?
DevsContext is an open-source MCP server (Python) that provides AI coding agents
with synthesized engineering context from SDLC tools (Jira, Fireflies, local docs).

When a developer asks their AI agent to work on a task, DevsContext fetches relevant
data on-demand from connected sources, synthesizes it via LLM into a structured
context block, and returns it through MCP.

## Architecture
- MCP server using the official Python MCP SDK (`mcp` package)
- On-demand fetching with optional pre-processing agent
- Sources: Jira REST API, Fireflies GraphQL API, Slack, Gmail, local markdown docs
- Synthesis: LLM (Claude Haiku / GPT-4o-mini / Ollama) combines raw data into structured block
- Cache: in-memory TTL cache + optional SQLite for pre-built context

### Plugin System
Source adapters and synthesis engines are plugins.
- Plugin interfaces defined in src/devscontext/plugins/base.py
- Built-in plugins: jira, fireflies, slack, gmail, local_docs
- External plugins: discovered via Python entry points (devscontext.plugins)
- Plugins are activated by being listed in .devscontext.yaml

### Pre-processing Agent
- Watches Jira for tickets entering a configurable status (default: "Ready for Development")
- Runs a multi-step pipeline: deep fetch → broad search → thorough matching → multi-pass synthesis
- Stores pre-built context in SQLite (.devscontext/cache.db)
- MCP server checks pre-built storage first, falls back to on-demand if not found
- Agent and MCP server are separate processes sharing the same SQLite file

### Fetch Strategy
Primary source (Jira) fetched first, then all secondary sources in parallel.
Each source plugin declares if it needs primary context via a needs_primary_context flag.

### Optional RAG
Disabled by default. When enabled via config, enhances local doc matching
with embedding-based semantic search. Requires: pip install devscontext[rag]
Index built manually: devscontext index-docs

### Tool Behaviors
- `get_task_context`: Full LLM synthesis, cached
- `search_context`: No LLM, no cache (fast freeform search)
- `get_standards`: No LLM, no cache (direct doc retrieval)

## Tech Stack
- Python 3.11+
- `mcp` - MCP Python SDK for server implementation
- `httpx` - async HTTP client for API calls
- `click` - CLI framework
- `pyyaml` - config parsing
- `pydantic` - data validation and models
- `aiosqlite` - async SQLite for pre-built context storage

### Optional Dependencies
All heavy deps are optional. Core install remains lightweight.
- `anthropic` / `openai` - LLM clients for synthesis
- `slack_sdk` - pip install devscontext[slack]
- `google-api-python-client` - pip install devscontext[gmail]
- `sentence-transformers` - pip install devscontext[rag]

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
- `src/devscontext/adapters/` - one file per source (jira.py, fireflies.py, slack.py, gmail.py, local_docs.py)
- `src/devscontext/plugins/` - plugin system (base.py, registry.py, synthesis.py)
- `src/devscontext/rag/` - optional RAG support (embeddings.py, index.py)
- `src/devscontext/synthesis.py` - LLM synthesis prompt and client
- `src/devscontext/cache.py` - in-memory TTL cache
- `src/devscontext/storage.py` - SQLite storage for pre-built context
- `src/devscontext/preprocessor.py` - pre-processing agent
- `src/devscontext/watcher.py` - Jira status watcher for agent
- `src/devscontext/config.py` - YAML config loading and validation
- `src/devscontext/cli.py` - CLI commands (init, test, serve, agent)
- `src/devscontext/utils.py` - text utilities (keyword extraction, truncation)

## MCP Tools (3 total)
1. `get_task_context(task_id: str)` - full synthesized context for a Jira ticket
2. `search_context(query: str)` - search across all sources by keyword
3. `get_standards(area: str | None)` - coding standards, optionally filtered

## Key Design Decisions
- On-demand fetching with optional pre-processing for instant retrieval
- No external vector DB - use NumPy + cosine similarity for optional RAG
- LLM synthesis happens at retrieval time (or pre-built by agent)
- Config via `.devscontext.yaml` in project root
- Auth credentials via environment variables only (never in config file)
- Graceful degradation: if a source is not configured, skip it and return available context
- Plugin architecture: adapters and synthesis engines are extensible

### Local Docs Matching
Local docs are matched to tickets via:
1. Components → doc filenames and headings
2. Labels → doc filenames and headings
3. Keywords from ticket title → doc content
4. Standards docs (CLAUDE.md, .cursorrules, standards/) are always included

Docs are classified by path:
- `architecture/`, `arch/` → architecture docs
- `standards/`, `style/`, `coding/` → coding standards
- `adr/`, `adrs/` → architecture decision records
- `CLAUDE.md`, `.cursorrules` → standards (special files)

## Testing
- Use pytest with pytest-asyncio
- Mock external APIs in tests (httpx mock)
- Test the synthesis prompt with fixture data

## Commands
- `devscontext init` - create .devscontext.yaml interactively
- `devscontext test` - fetch a sample ticket and show synthesized output
- `devscontext serve` - start MCP server (stdio transport)
- `devscontext agent start` - start pre-processing agent (watches Jira)
- `devscontext agent run-once` - process all matching tickets once
- `devscontext agent status` - show agent and storage status
- `devscontext agent process TICKET-123` - process a specific ticket
- `devscontext index-docs` - build RAG index for local docs (requires [rag])
