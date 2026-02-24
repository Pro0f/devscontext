# DevsContext

MCP server that gives AI coding agents synthesized engineering context — requirements, decisions, architecture, and standards — from your actual tools.

## The Problem

AI coding agents lack context. They don't know your team's decisions, architecture patterns, or coding standards. Connecting raw MCP servers floods them with irrelevant data they can't prioritize. Large companies build internal context infrastructure. DevsContext brings that to everyone.

## What You Get

When you say "work on PROJ-123" in Claude Code, DevsContext fetches from Jira, meeting transcripts, and your docs, then synthesizes it into this:

```markdown
## Task: PROJ-123 — Add retry logic to payment webhook handler

### Requirements
1. Implement exponential backoff for failed webhook deliveries
2. Max 5 retry attempts over 24 hours
3. Dead-letter queue for permanently failed webhooks
4. Metrics for retry success/failure rates

Acceptance criteria: [Jira PROJ-123]
- [ ] Webhooks retry with exponential backoff (1min, 5min, 30min, 2hr, 12hr)
- [ ] Failed webhooks move to DLQ after 5 attempts
- [ ] Dashboard shows retry metrics

### Key Decisions
- **Use SQS with visibility timeout** for retry scheduling, not cron jobs.
  Decided by @sarah in March 15 sprint planning. Rationale: SQS handles
  timing natively, reduces operational overhead. [Meeting: Sprint 23 Planning]

- **Exponential backoff schedule**: 1min → 5min → 30min → 2hr → 12hr.
  Based on payment processor rate limits. [Comment by @mike, Mar 16]

### Architecture Context
Webhook flow: `PaymentController` → `WebhookService.dispatch()` → SQS queue
→ `WebhookWorker.process()` → external endpoint.

Add retry logic in `WebhookWorker.process()` at:
`src/workers/webhook_worker.ts:45-80`

DLQ table schema in `migrations/004_webhook_dlq.sql`. [Architecture: payments-service.md]

### Coding Standards
- Use `Result<T, WebhookError>` pattern, don't throw exceptions
- Retry delays: use `calculateBackoff(attempt)` helper from `src/utils/retry.ts`
- Tests: mock SQS with `@aws-sdk/client-sqs-mock`, see `tests/workers/` for examples
[Standards: typescript.md, testing.md]

### Related Work
- PROJ-456: "Payment webhook initial implementation" (Done) — base implementation
- PROJ-789: "Add webhook monitoring dashboard" (In Progress) — will consume the metrics
```

One synthesized block. Everything the AI needs to write correct code.

## Quick Start

```bash
pip install devscontext
devscontext init
```

Set your credentials:
```bash
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-token"
export ANTHROPIC_API_KEY="your-key"  # for synthesis
```

Connect to Claude Code:
```bash
claude mcp add devscontext -- devscontext serve
```

Then in Claude Code:
```
> work on PROJ-123
```

## Supported Sources

| Source | What's Fetched |
|--------|----------------|
| **Jira** | Ticket details, comments, linked issues, acceptance criteria |
| **Fireflies** | Meeting transcripts, decisions, action items |
| **Local Docs** | Architecture docs, coding standards, ADRs |

Coming soon: Linear, Notion, Confluence, Slack threads

## Configuration

DevsContext uses `.devscontext.yaml` in your project root:

```yaml
adapters:
  jira:
    enabled: true
    base_url: "https://your-company.atlassian.net"
    email: "${JIRA_EMAIL}"
    api_token: "${JIRA_API_TOKEN}"

  fireflies:
    enabled: false  # Optional
    api_key: "${FIREFLIES_API_KEY}"

  local_docs:
    enabled: true
    paths:
      - "./docs"
      - "./CLAUDE.md"

synthesis:
  provider: "anthropic"
  model: "claude-3-haiku-20240307"
```

See [.devscontext.yaml.example](.devscontext.yaml.example) for all options.

## How It Works

1. **Fetch**: When you mention a ticket, DevsContext fetches from all configured sources in parallel
2. **Extract**: It finds relevant content — ticket matches docs by component/label, searches meeting transcripts for keywords
3. **Synthesize**: An LLM combines raw data into a structured context block with sources cited

No background processes. No vector database. Just on-demand fetching and synthesis.

## MCP Tools

| Tool | When to Use | Example |
|------|-------------|---------|
| `get_task_context` | Starting work on a ticket | "work on PROJ-123" |
| `search_context` | Questions about architecture or past decisions | "how do we handle payment retries?" |
| `get_standards` | Checking coding conventions | "what are our testing standards?" |

## Development

```bash
git clone https://github.com/anthropics/devscontext.git
cd devscontext
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check . && mypy src/
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Ideas for contributions:
- New adapters (Linear, Notion, Confluence)
- Better keyword extraction
- Caching improvements

## License

MIT
