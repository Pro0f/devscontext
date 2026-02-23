# DevsContext

An MCP (Model Context Protocol) server that aggregates context from multiple sources to help AI coding assistants understand the full picture of development tasks.

## Features

- **Jira Integration**: Fetch ticket details, acceptance criteria, and related context
- **Meeting Transcripts**: Search Fireflies.ai transcripts for relevant discussions
- **Local Documentation**: Index and search project documentation
- **Intelligent Synthesis**: Combine and rank context from multiple sources
- **Caching**: TTL-based cache to minimize API calls

## Installation

```bash
pip install devscontext
```

Or install from source:

```bash
git clone https://github.com/your-org/devscontext.git
cd devscontext
pip install -e ".[dev]"
```

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

## Usage with Claude Code

Add to your Claude Code MCP configuration (`~/.config/claude-code/config.json`):

```json
{
  "mcpServers": {
    "devscontext": {
      "command": "devscontext",
      "args": ["serve"]
    }
  }
}
```

Then use the `get_task_context` tool:

```
Use get_task_context with task_id "PROJ-123" to understand what I need to implement.
```

## Available Tools

### get_task_context

Fetches aggregated context for a development task.

**Parameters:**
- `task_id` (required): The task identifier (e.g., "PROJ-123")
- `refresh` (optional): Force refresh, bypassing cache

### health_check

Returns the health status of all configured adapters.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run the MCP server
devscontext serve

# Run tests
pytest

# Type checking
mypy src/devscontext

# Linting
ruff check src/
```

## License

MIT License - see [LICENSE](LICENSE) for details.
