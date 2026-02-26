# Configuration Reference

DevsContext uses `.devscontext.yaml` for all configuration. This file should be placed in your project root.

## File Location

DevsContext searches for `.devscontext.yaml` in the current directory and parent directories, similar to how git finds `.gitconfig`.

## Environment Variables

Use `${VAR_NAME}` or `$VAR_NAME` syntax to reference environment variables. This is required for sensitive values like API keys:

```yaml
sources:
  jira:
    api_token: "${JIRA_API_TOKEN}"
```

---

## Configuration Schema

### sources

Configuration for data source adapters.

#### sources.jira

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable Jira adapter |
| `base_url` | string | `""` | Jira instance URL (e.g., `https://company.atlassian.net`) |
| `email` | string | `""` | Authentication email |
| `api_token` | string | `""` | Jira API token (use `${JIRA_API_TOKEN}`) |
| `project` | string | `""` | Default project key for queries |
| `primary` | bool | `true` | Fetch first; share context with secondary sources |

#### sources.fireflies

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable Fireflies adapter |
| `api_key` | string | `""` | Fireflies API key (use `${FIREFLIES_API_KEY}`) |
| `primary` | bool | `false` | Whether this is a primary source |

#### sources.docs

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable local docs adapter |
| `paths` | list[string] | `["./docs/"]` | Paths to documentation directories |
| `standards_path` | string | `null` | Optional path to coding standards |
| `architecture_path` | string | `null` | Optional path to architecture docs |
| `primary` | bool | `false` | Whether this is a primary source |
| `rag` | object | `null` | Optional RAG configuration (see below) |

##### sources.docs.rag

Optional embedding-based search configuration. Requires `pip install devscontext[rag]`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable RAG for semantic doc matching |
| `embedding_provider` | string | `"local"` | Provider: `local`, `openai`, or `ollama` |
| `embedding_model` | string | `"all-MiniLM-L6-v2"` | Model for generating embeddings |
| `index_path` | string | `".devscontext/doc_index.json"` | Path to embedding index file |
| `top_k` | int | `10` | Number of similar sections to retrieve |
| `similarity_threshold` | float | `0.3` | Minimum similarity score (0-1) |

#### sources.slack

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable Slack adapter |
| `bot_token` | string | `""` | Slack bot token (use `${SLACK_BOT_TOKEN}`) |
| `channels` | list[string] | `[]` | Channel names to search |
| `include_threads` | bool | `true` | Fetch full threads for matches |
| `max_messages` | int | `20` | Max messages per search (1-100) |
| `lookback_days` | int | `30` | Days to search back (1-90) |
| `primary` | bool | `false` | Whether this is a primary source |

#### sources.gmail

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable Gmail adapter |
| `credentials_path` | string | `""` | Path to OAuth2 credentials JSON |
| `token_path` | string | `".devscontext/gmail_token.json"` | Path for OAuth2 refresh token |
| `search_scope` | string | `"newer_than:30d"` | Gmail search scope filter |
| `max_results` | int | `10` | Max emails to return (1-50) |
| `labels` | list[string] | `["INBOX"]` | Labels to search within |
| `primary` | bool | `false` | Whether this is a primary source |

---

### synthesis

Configuration for context synthesis.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `plugin` | string | `"llm"` | Synthesis plugin: `llm`, `template`, `passthrough` |
| `provider` | string | `"anthropic"` | LLM provider: `anthropic`, `openai`, `ollama` |
| `model` | string | `"claude-haiku-4-5"` | Model name/ID |
| `api_key` | string | `null` | API key (use env var, e.g., `${ANTHROPIC_API_KEY}`) |
| `max_output_tokens` | int | `3000` | Max tokens in synthesized output (100-10000) |
| `temperature` | float | `0.0` | LLM temperature (0.0-2.0) |
| `prompt_template` | string | `null` | Path to custom prompt template |
| `template_path` | string | `null` | Jinja2 template path (for `template` plugin) |

---

### cache

In-memory cache configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable caching |
| `ttl_minutes` | int | `15` | Cache TTL in minutes (1-1440) |
| `max_size` | int | `100` | Maximum cache entries |

---

### agents

Background agent configuration.

#### agents.preprocessor

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable preprocessing agent |
| `jira_status` | string | `"Ready for Development"` | Jira status that triggers processing |
| `jira_project` | string or list | `""` | Project key(s) to watch |
| `context_ttl_hours` | int | `24` | How long pre-built context is valid (1-168) |

#### agents.preprocessor.trigger

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `"polling"` | Trigger type (only `polling` supported) |
| `poll_interval_minutes` | int | `5` | Poll interval (1-60 minutes) |

---

### storage

Persistent storage configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | `".devscontext/cache.db"` | SQLite database path |

---

## Example Configurations

### Minimal (Jira + Local Docs)

```yaml
sources:
  jira:
    enabled: true
    base_url: "https://company.atlassian.net"
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

### Full Configuration

```yaml
sources:
  jira:
    enabled: true
    base_url: "https://company.atlassian.net"
    email: "${JIRA_EMAIL}"
    api_token: "${JIRA_API_TOKEN}"
    project: "PROJ"
    primary: true

  fireflies:
    enabled: true
    api_key: "${FIREFLIES_API_KEY}"
    primary: false

  docs:
    enabled: true
    paths:
      - "./docs"
      - "./CLAUDE.md"
    standards_path: "./docs/standards"
    architecture_path: "./docs/architecture"
    primary: false
    rag:
      enabled: true
      embedding_provider: "local"
      embedding_model: "all-MiniLM-L6-v2"
      index_path: ".devscontext/doc_index.json"
      top_k: 10
      similarity_threshold: 0.3

  slack:
    enabled: true
    bot_token: "${SLACK_BOT_TOKEN}"
    channels:
      - "engineering"
      - "payments-team"
    include_threads: true
    max_messages: 20
    lookback_days: 30

  gmail:
    enabled: false
    credentials_path: "${GMAIL_CREDENTIALS_PATH}"
    token_path: ".devscontext/gmail_token.json"
    search_scope: "newer_than:30d"
    max_results: 10
    labels:
      - "INBOX"

synthesis:
  plugin: "llm"
  provider: "anthropic"
  model: "claude-haiku-4-5"
  max_output_tokens: 3000
  temperature: 0.0

cache:
  enabled: true
  ttl_minutes: 15
  max_size: 100

agents:
  preprocessor:
    enabled: true
    jira_status: "Ready for Development"
    jira_project: "PROJ"
    context_ttl_hours: 24
    trigger:
      type: "polling"
      poll_interval_minutes: 5

storage:
  path: ".devscontext/cache.db"
```

### With RAG Enabled

```yaml
sources:
  docs:
    enabled: true
    paths:
      - "./docs"
    rag:
      enabled: true
      embedding_provider: "local"  # Uses sentence-transformers
      embedding_model: "all-MiniLM-L6-v2"
      top_k: 10
      similarity_threshold: 0.3

synthesis:
  provider: "anthropic"
  model: "claude-haiku-4-5"
```

After configuring RAG, build the index:

```bash
pip install devscontext[rag]
devscontext index-docs
```
