# Cursor Setup Guide

This guide walks you through setting up DevsContext with Cursor IDE.

## Prerequisites

- Python 3.11 or higher
- Cursor IDE (any recent version with MCP support)

## Step 1: Install DevsContext

```bash
pip install devscontext
```

Verify installation:
```bash
devscontext --version
```

## Step 2: Create Configuration

Create `.devscontext.yaml` in your project root:

```bash
devscontext init
```

Or create manually:

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

synthesis:
  provider: "anthropic"
  model: "claude-haiku-4-5"
```

Set environment variables:
```bash
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-token"
export ANTHROPIC_API_KEY="your-key"
```

## Step 3: Add to Cursor

### Option A: GUI

1. Open Cursor
2. Go to **Cursor > Settings > Cursor Settings**
3. Click **Tools & Integrations** in the sidebar
4. Under **MCP Tools**, click **New MCP Server**
5. Enter:
   - Name: `devscontext`
   - Command: `devscontext`
   - Arguments: `serve`

### Option B: Config File

Create or edit `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project):

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

## Step 4: Verify It Works

1. Open a new Cursor chat (Cmd/Ctrl + L)
2. Type: "work on PROJ-123" (replace with a real ticket ID)
3. Cursor should call `get_task_context` and show synthesized context

## Example Prompts

| Prompt | Tool Called |
|--------|-------------|
| "work on PROJ-123" | `get_task_context` |
| "start ticket PROJ-456" | `get_task_context` |
| "how do we handle payment retries?" | `search_context` |
| "what was decided about webhooks?" | `search_context` |
| "what are our testing standards?" | `get_standards` |

## Demo Mode (No Config Needed)

Try DevsContext without any API keys:

```json
{
  "mcpServers": {
    "devscontext-demo": {
      "command": "devscontext",
      "args": ["serve", "--demo"]
    }
  }
}
```

This uses sample data for a payments webhook ticket (PROJ-123).

## Troubleshooting

### Server not appearing

- Restart Cursor after adding the config
- Check that `devscontext` is in your PATH: `which devscontext`

### "Command not found"

- Use the full path: `"command": "/path/to/devscontext"`
- Find the path with: `which devscontext`
- Or activate your virtual environment in the command

### View logs

- Press Cmd/Ctrl + Shift + P
- Search for "Developer: Show Logs..."
- Look for MCP-related messages

### Environment variables not loaded

If credentials aren't being picked up:

1. Ensure variables are exported in your shell profile (`~/.zshrc`, `~/.bashrc`)
2. Restart Cursor completely (not just reload)
3. Or pass them directly in the config:

```json
{
  "mcpServers": {
    "devscontext": {
      "command": "devscontext",
      "args": ["serve"],
      "env": {
        "JIRA_EMAIL": "you@company.com",
        "JIRA_API_TOKEN": "your-token",
        "ANTHROPIC_API_KEY": "your-key"
      }
    }
  }
}
```

## Next Steps

- [Configuration Reference](configuration.md) - Full config options
- [Plugin System](plugins.md) - Add custom adapters
- [Pre-processing Agent](pre-processing.md) - Build context proactively
