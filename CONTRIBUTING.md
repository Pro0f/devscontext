# Contributing to DevsContext

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/anthropics/devscontext.git
cd devscontext
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/
```

## Code Style

We use ruff for linting and formatting:

```bash
ruff check .
ruff format .
mypy src/
```

## Pull Requests

1. Fork the repo and create a branch from `main`
2. Add tests for any new functionality
3. Ensure tests pass and code is formatted
4. Submit a PR with a clear description

## Adding a New Adapter

Adapters live in `src/devscontext/adapters/`. To add a new source:

1. Create `adapters/your_source.py` extending `Adapter` base class
2. Implement `fetch_context()`, `health_check()`, and any source-specific methods
3. Add configuration model to `config.py`
4. Wire into `DevsContextCore` in `core.py`
5. Add tests in `tests/test_your_source.py`

See `adapters/jira.py` as a reference implementation.

## Questions?

Open an issue or start a discussion.
