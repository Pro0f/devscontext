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

1. Create `src/devscontext/adapters/your_source.py`:
   - Extend the `Adapter` base class
   - Implement `fetch_context(task_id)` and `health_check()`
   - Add any source-specific methods (e.g., `search()`)

2. Add config model to `src/devscontext/config.py`

3. Wire into `src/devscontext/core.py`:
   - Add adapter initialization
   - Include in fetch/search flows

4. Add tests in `tests/test_your_source.py`

See `adapters/jira.py` as reference.

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
