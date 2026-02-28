# DevsContext

MCP server that gives AI coding agents synthesized engineering context — requirements, decisions, architecture, and standards — from your actual tools.

## The Problem

AI coding agents lack context. They don't know your team's decisions, architecture patterns, or coding standards. Connecting raw MCP servers floods them with irrelevant data they can't prioritize. Large companies build internal context infrastructure. DevsContext brings that to everyone.

## Try It Now

```bash
pip install devscontext
devscontext demo
```

No API keys needed. Shows synthesized context for a sample payments ticket.

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

## Works With

| IDE / Tool | Setup Guide | Status |
|-----------|-------------|--------|
| Claude Code | [Quick Start](#quick-start) | Tested |
| Cursor | [Setup Guide](docs/cursor-setup.md) | Tested |
| Windsurf | [Setup Guide](docs/windsurf-setup.md) | Tested |
| Any MCP client | `devscontext serve` via stdio | Compatible |

## Supported Sources

| Source | What's Fetched | Status |
|--------|----------------|--------|
| **Jira** | Ticket details, comments, linked issues, acceptance criteria | Stable |
| **Fireflies** | Meeting transcripts, decisions, action items | Stable |
| **Local Docs** | Architecture docs, coding standards, ADRs | Stable |
| **Slack** | Channel discussions, threads, decisions | New |
| **Gmail** | Email threads related to tickets | New |

Coming soon: Linear, Notion, Confluence

## Pre-processing Agent

Build context proactively before developers pick up tickets:

```bash
# Start the agent (polls Jira for ready tickets)
devscontext agent start

# Single run for CI/cron
devscontext agent run-once

# Check pre-built context status
devscontext agent status
```

Configure in `.devscontext.yaml`:

```yaml
agents:
  preprocessor:
    enabled: true
    jira_status: "Ready for Development"
    jira_project: "PROJ"
```

See [docs/pre-processing.md](docs/pre-processing.md) for the full guide.

## Plugin System

DevsContext uses a plugin architecture for adapters and synthesis:

- **Adapters**: Fetch context from sources (Jira, Slack, docs, etc.)
- **Synthesis Plugins**: Combine context (LLM, template, passthrough)

See [docs/plugins.md](docs/plugins.md) for creating custom plugins.

## Configuration

DevsContext uses `.devscontext.yaml` in your project root:

```yaml
sources:
  jira:
    enabled: true
    base_url: "https://your-company.atlassian.net"
    email: "${JIRA_EMAIL}"
    api_token: "${JIRA_API_TOKEN}"

  docs:
    enabled: true
    paths:
      - "./docs"
      - "./CLAUDE.md"

  slack:
    enabled: true
    bot_token: "${SLACK_BOT_TOKEN}"
    channels: ["engineering", "payments-team"]

synthesis:
  provider: "anthropic"
  model: "claude-haiku-4-5"
```

Full configuration reference: [docs/configuration.md](docs/configuration.md)

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
git clone https://github.com/Pro0f/devscontext.git
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
