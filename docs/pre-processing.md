# Pre-processing Agent Guide

The pre-processing agent builds context proactively for Jira tickets before developers pick them up. This eliminates wait time and ensures rich context is available instantly.

## How It Works

```
┌──────────────┐     ┌─────────────────┐     ┌────────────────────┐
│    Jira      │     │   JiraWatcher   │     │  Preprocessing     │
│   (Tickets)  │────▶│   (Polling)     │────▶│    Pipeline        │
└──────────────┘     └─────────────────┘     └──────────┬─────────┘
                                                        │
                                                        ▼
                     ┌──────────────────────────────────────────────┐
                     │        PrebuiltContextStorage (SQLite)       │
                     │  ┌─────────────────────────────────────────┐ │
                     │  │ task_id │ synthesized │ quality │ gaps  │ │
                     │  │ PROJ-1  │ "## Task.." │  0.85   │ [...]  │ │
                     │  │ PROJ-2  │ "## Task.." │  0.70   │ [...]  │ │
                     │  └─────────────────────────────────────────┘ │
                     └──────────────────────────────────────────────┘
```

1. **JiraWatcher** polls Jira for tickets in a target status (e.g., "Ready for Development")
2. **PreprocessingPipeline** fetches context from all adapters and synthesizes it
3. **PrebuiltContextStorage** stores the pre-built context in SQLite
4. When an AI agent requests context, it's served instantly from storage

## Benefits

### Instant Context
Pre-built context is served in milliseconds instead of seconds. No waiting for API calls.

### Quality Scoring
Each pre-built context includes a quality score (0-1) based on:
- Presence of acceptance criteria
- Component/label coverage
- Related meeting context
- Documentation matches

### Gap Identification
The agent identifies missing context before work starts:
- "No acceptance criteria defined"
- "No related meetings found"
- "No architecture docs for this component"

### Staleness Detection
Context is automatically refreshed when the Jira ticket is updated (tracked via `source_data_hash`).

---

## Configuration

Add to `.devscontext.yaml`:

```yaml
agents:
  preprocessor:
    enabled: true
    jira_status: "Ready for Development"
    jira_project: "PROJ"  # or ["PROJ", "TEAM"] for multiple
    context_ttl_hours: 24
    trigger:
      type: "polling"
      poll_interval_minutes: 5

storage:
  path: ".devscontext/cache.db"
```

### Configuration Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable the preprocessing agent |
| `jira_status` | string | `"Ready for Development"` | Jira status that triggers processing |
| `jira_project` | string or list | `""` | Project key(s) to watch |
| `context_ttl_hours` | int | `24` | How long pre-built context is valid |
| `trigger.type` | string | `"polling"` | Trigger type (only `polling` supported) |
| `trigger.poll_interval_minutes` | int | `5` | How often to poll Jira |

---

## CLI Commands

### Start Polling Agent

Run the agent in the foreground. It will poll Jira continuously until stopped with Ctrl+C.

```bash
devscontext agent start
```

Output:
```
DevsContext Agent

→ Polling every 5 minutes
→ Watching for status: Ready for Development
→ Project(s): PROJ

✓ Agent started. Press Ctrl+C to stop.

Processing PROJ-123...
✓ PROJ-123: quality=85%, 0 gaps
Processing PROJ-124...
✓ PROJ-124: quality=70%, 2 gaps
```

### Single Run (for CI/Cron)

Process any new tickets once and exit. Useful for scheduled jobs.

```bash
devscontext agent run-once
```

Output:
```
DevsContext Agent - Single Run

✓ Processed 3 ticket(s).
```

### Check Status

View statistics about stored pre-built context.

```bash
devscontext agent status
```

Output:
```
Pre-built Context Storage

  Total contexts:       12
  Active (not expired): 10
  Expired:              2
  Average quality:      78.5%
  Last build:           2024-03-20T14:30:00

→ Storage path: .devscontext/cache.db
```

### Manual Processing

Process a specific ticket immediately, bypassing the watcher.

```bash
devscontext agent process PROJ-123
```

Output:
```
Processing PROJ-123

✓ Processed in 2.3s

  Quality score: 85.0%
  Sources used:  3

✓ No gaps identified - context is complete!
```

Or if gaps are found:
```
Processing PROJ-124

✓ Processed in 1.8s

  Quality score: 70.0%
  Sources used:  2

Identified gaps:
  - No acceptance criteria defined
  - No related meetings found
```

---

## Context Quality Scoring

Quality scores help identify tickets that may need more context before work begins.

### Scoring Factors

| Factor | Weight | Description |
|--------|--------|-------------|
| Acceptance Criteria | 25% | Presence of AC in ticket |
| Components | 15% | Ticket has components assigned |
| Labels | 10% | Ticket has labels |
| Meeting Context | 20% | Related meetings found |
| Documentation | 20% | Related docs found |
| Linked Issues | 10% | Has linked issues |

### Score Interpretation

| Score | Meaning |
|-------|---------|
| 90-100% | Excellent - Rich context available |
| 70-89% | Good - Most context available |
| 50-69% | Fair - Some gaps identified |
| < 50% | Poor - Significant context missing |

### Gap Types

The agent identifies these gap types:
- `"No acceptance criteria defined"`
- `"No components assigned"`
- `"No related meetings found"`
- `"No documentation matches"`
- `"No linked issues"`

---

## Deployment Patterns

### Local Development

Run the agent in a terminal while developing:

```bash
devscontext agent start
```

### Cron Job

Add to crontab for periodic processing:

```bash
# Process every 15 minutes during work hours
*/15 9-18 * * 1-5 cd /path/to/project && devscontext agent run-once >> /var/log/devscontext.log 2>&1
```

### CI Pipeline

Add a scheduled job in your CI (GitHub Actions example):

```yaml
name: Pre-process Context
on:
  schedule:
    - cron: '*/15 9-18 * * 1-5'  # Every 15 min, work hours

jobs:
  preprocess:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install devscontext[anthropic]
      - run: devscontext agent run-once
        env:
          JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
          JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Systemd Service

For production deployments on Linux:

```ini
# /etc/systemd/system/devscontext-agent.service
[Unit]
Description=DevsContext Pre-processing Agent
After=network.target

[Service]
Type=simple
User=devscontext
WorkingDirectory=/opt/devscontext
ExecStart=/opt/devscontext/venv/bin/devscontext agent start
Restart=always
RestartSec=10
Environment=JIRA_EMAIL=your-email@company.com
Environment=JIRA_API_TOKEN=your-token
Environment=ANTHROPIC_API_KEY=your-key

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable devscontext-agent
sudo systemctl start devscontext-agent
```

---

## Troubleshooting

### Agent Not Finding Tickets

1. Verify Jira configuration:
   ```bash
   devscontext test
   ```

2. Check the status name matches exactly:
   ```yaml
   agents:
     preprocessor:
       jira_status: "Ready for Development"  # Must match Jira exactly
   ```

3. Verify project key:
   ```yaml
   agents:
     preprocessor:
       jira_project: "PROJ"  # Check this is correct
   ```

### Low Quality Scores

- Ensure all adapters are configured (Fireflies, Slack, etc.)
- Check that documentation paths are correct
- Verify tickets have components/labels assigned

### Storage Issues

Clear and rebuild storage:
```bash
rm -rf .devscontext/cache.db
devscontext agent run-once
```
