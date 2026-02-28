# Windsurf Setup Guide

This guide walks you through setting up DevsContext with Windsurf IDE.

## Prerequisites

- Python 3.11 or higher
- Windsurf IDE (any recent version with MCP support)

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

## Step 3: Add to Windsurf

### Option A: GUI

1. Open Windsurf
2. Go to **Settings > Advanced Settings**
   - Or use Command Palette: **Open Windsurf Settings Page**
3. Scroll to the **Cascade** section
4. Click **Add new server**
5. Enter:
   - Name: `devscontext`
   - Command: `devscontext`
   - Arguments: `serve`

### Option B: Config File

Edit `~/.codeium/windsurf/mcp_config.json`:

**macOS/Linux:**
```bash
mkdir -p ~/.codeium/windsurf
```

**Windows:**
```powershell
mkdir -Force "$env:USERPROFILE\.codeium\windsurf"
```

Add the configuration:

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

1. Open Cascade chat in Windsurf
2. Type: "work on PROJ-123" (replace with a real ticket ID)
3. Cascade should call `get_task_context` and show synthesized context

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

- Restart Windsurf after adding the config
- Check that `devscontext` is in your PATH: `which devscontext`

### "Command not found"

- Use the full path: `"command": "/path/to/devscontext"`
- Find the path with: `which devscontext`

### Tool limit reached

Windsurf has a 100-tool limit across all MCP servers. If you hit this limit:

1. Go to **Settings > Advanced Settings > Cascade**
2. Disable tools you don't need from other MCP servers

### View logs

- Check Windsurf's developer console for MCP errors
- Look in the Cascade section of settings for server status

### Environment variables not loaded

If credentials aren't being picked up:

1. Ensure variables are exported in your shell profile (`~/.zshrc`, `~/.bashrc`)
2. Restart Windsurf completely (not just reload)
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
