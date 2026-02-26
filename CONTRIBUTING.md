# Contributing to DevsContext

## Development Setup

```bash
git clone https://github.com/Pro0f/devscontext.git
cd devscontext
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

Configure for local testing:
```bash
cp .devscontext.yaml.example .devscontext.yaml
# Edit .devscontext.yaml with your Jira URL
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-token"
```

## Running Tests

Unit tests (no API keys needed):
```bash
pytest tests/ --ignore=tests/test_integration.py
```

Integration tests (requires real API keys):
```bash
pytest tests/test_integration.py
```

## Adding a New Adapter

1. **Create adapter file** `src/devscontext/adapters/your_source.py`:
   - Extend the `Adapter` base class from `plugins/base.py`
   - Set class attributes: `name`, `source_type`, `config_schema`
   - Implement required methods:
     - `fetch_task_context(task_id, ticket=None) -> SourceContext`
     - `search(query, max_results) -> list[SearchResult]`
     - `health_check() -> bool`
   - Optionally implement `close()` and `format_for_synthesis()`

2. **Add config model** to `src/devscontext/models.py`:
   - Create Pydantic model with `enabled`, `primary` fields
   - Add to `SourcesConfig`

3. **Register in plugin registry** `src/devscontext/plugins/registry.py`:
   - Add to `register_builtin_plugins()` method
   - Add loading logic in `load_from_config()`

4. **Add tests** in `tests/test_your_source.py`

See `adapters/slack.py` as a complete reference for communication sources.

For full details, see [docs/plugins.md](docs/plugins.md).

## Plugin Development

DevsContext uses a plugin system for extensibility:

- **Adapters**: Fetch context from data sources
- **Synthesis Plugins**: Process and combine context

External plugins can be published as pip packages using entry points.
See [docs/plugins.md](docs/plugins.md) for the complete guide.

## Testing Adapters

```bash
# Unit tests (no API keys needed)
pytest tests/test_your_source.py

# Test with real API (integration)
devscontext test --task YOUR-123
```

## Testing Pre-processing Agent

```bash
# Process a single ticket
devscontext agent process TEST-123

# Check storage status
devscontext agent status
```

## Code Quality

Before submitting:
```bash
ruff check .
ruff format .
mypy src/
pytest tests/ --ignore=tests/test_integration.py
```

Requirements:
- Type hints on all functions
- Pydantic models for data structures
- Tests for new functionality

## Pull Requests

1. Fork and create a branch from `main`
2. Make your changes with tests
3. Ensure all checks pass
4. Open a PR describing what and why

## Questions?

Open an issue.
