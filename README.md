# DevsContext

**Synthesized engineering context for AI coding agents.**

DevsContext is an open-source MCP server that gives AI coding tools (Claude Code,
Cursor, etc.) the full picture when working on a task — requirements, team decisions,
architecture patterns, and coding standards — all in one synthesized context block.

> Large tech companies build this internally. DevsContext brings it to everyone.

## The Problem

AI coding agents are smart but lack context. They don't know:
- Why a feature was decided on (from your sprint planning meeting)
- How your team structures code (from your architecture docs)
- What coding patterns to follow (from your style guides)

Connecting individual MCP servers (Jira, Confluence, etc.) helps, but the AI
gets flooded with raw data and picks up irrelevant context.

## The Solution

DevsContext fetches from your tools, extracts what's relevant, and synthesizes
it into a clean context block — so your AI agent knows *what* to build, *why*
it was decided, and *how* it should be written.

## Quick Start

```bash
pip install devscontext
devscontext init
claude mcp add devscontext -- devscontext serve
```

Then in Claude Code:

```
work on PROJ-1234
```

Claude automatically gets the full context.

## Configuration

Create a `.devscontext.yaml` file in your project root:

```yaml
adapters:
  jira:
    enabled: true
    base_url: "https://your-company.atlassian.net"
    email: "your-email@company.com"
    api_token: "${JIRA_API_TOKEN}"

  fireflies:
    enabled: false
    api_key: "${FIREFLIES_API_KEY}"

  local_docs:
    enabled: true
    paths:
      - "./docs"

cache:
  ttl_seconds: 300
  max_size: 100
```

## Available Tools

| Tool | Description |
|------|-------------|
| `get_task_context` | Full synthesized context for a Jira ticket |
| `search_context` | Search across all sources by keyword |
| `get_standards` | Coding standards from local documentation |

## Development

```bash
# Install from source
git clone https://github.com/yourusername/devscontext.git
cd devscontext
pip install -e ".[dev]"

# Run the MCP server
devscontext serve

# Run tests
pytest

# Linting
ruff check src/
```

## Status

Early development — contributions welcome!

## License

MIT
