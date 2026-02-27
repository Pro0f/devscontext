"""CLI entry point for DevsContext.

This module provides the command-line interface for DevsContext,
including commands for initialization, testing, and running the server.

Commands:
    init: Create configuration file interactively
    test: Test connection to configured adapters
    serve: Start the MCP server (default)

Example:
    devscontext init
    devscontext test --task PROJ-123
    devscontext serve
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import click

from devscontext import __version__


def _success(msg: str) -> str:
    """Format success message with green checkmark."""
    return click.style("✓", fg="green") + " " + msg


def _error(msg: str) -> str:
    """Format error message with red X."""
    return click.style("✗", fg="red") + " " + msg


def _info(msg: str) -> str:
    """Format info message with blue arrow."""
    return click.style("→", fg="blue") + " " + msg


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="devscontext")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """DevsContext - MCP server for AI coding context.

    Provides synthesized engineering context from Jira, meeting transcripts,
    and local documentation to AI coding assistants.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose

    if ctx.invoked_subcommand is None:
        ctx.invoke(serve)


@cli.command()
def init() -> None:
    """Create .devscontext.yaml configuration interactively."""
    config_path = Path(".devscontext.yaml")
    gitignore_path = Path(".gitignore")

    if config_path.exists():
        click.echo(f"Config file already exists: {config_path}")
        if not click.confirm("Overwrite?", default=False):
            click.echo("Aborted.")
            return

    click.echo()
    click.echo(click.style("DevsContext Setup", bold=True))
    click.echo()

    # Jira configuration
    jira_enabled = click.confirm("Configure Jira?", default=True)
    jira_url = ""
    if jira_enabled:
        jira_url = click.prompt(
            "  Jira URL",
            default="https://your-company.atlassian.net",
        )
        click.echo("  " + _info("Set JIRA_EMAIL and JIRA_API_TOKEN environment variables"))

    # Fireflies configuration
    click.echo()
    fireflies_enabled = click.confirm("Configure Fireflies (meeting transcripts)?", default=False)
    if fireflies_enabled:
        click.echo("  " + _info("Set FIREFLIES_API_KEY environment variable"))

    # Local docs configuration
    click.echo()
    docs_enabled = click.confirm("Configure local docs?", default=True)
    docs_paths: list[str] = []
    if docs_enabled:
        default_paths = "./docs"
        if Path("CLAUDE.md").exists():
            default_paths = "./docs, ./CLAUDE.md"
        paths_input = click.prompt("  Doc paths (comma-separated)", default=default_paths)
        docs_paths = [p.strip() for p in paths_input.split(",") if p.strip()]

    # Build config
    config_lines = [
        "# DevsContext Configuration",
        "",
        "adapters:",
        "  jira:",
        f"    enabled: {str(jira_enabled).lower()}",
    ]

    if jira_enabled:
        config_lines.extend(
            [
                f'    base_url: "{jira_url}"',
                '    email: "${JIRA_EMAIL}"',
                '    api_token: "${JIRA_API_TOKEN}"',
            ]
        )

    config_lines.extend(
        [
            "",
            "  fireflies:",
            f"    enabled: {str(fireflies_enabled).lower()}",
        ]
    )

    if fireflies_enabled:
        config_lines.append('    api_key: "${FIREFLIES_API_KEY}"')

    config_lines.extend(
        [
            "",
            "  local_docs:",
            f"    enabled: {str(docs_enabled).lower()}",
        ]
    )

    if docs_enabled and docs_paths:
        config_lines.append("    paths:")
        for path in docs_paths:
            config_lines.append(f'      - "{path}"')

    config_lines.extend(
        [
            "",
            "synthesis:",
            '  provider: "anthropic"',
            '  model: "claude-3-haiku-20240307"',
            "",
            "cache:",
            "  ttl_seconds: 300",
            "  max_size: 100",
            "",
        ]
    )

    config_content = "\n".join(config_lines)
    config_path.write_text(config_content)

    # Add to .gitignore if not already there
    gitignore_updated = False
    if gitignore_path.exists():
        gitignore_content = gitignore_path.read_text()
        if ".devscontext.yaml" not in gitignore_content:
            with gitignore_path.open("a") as f:
                if not gitignore_content.endswith("\n"):
                    f.write("\n")
                f.write("\n# DevsContext config (contains env var references)\n")
                f.write(".devscontext.yaml\n")
            gitignore_updated = True
    else:
        gitignore_path.write_text("# DevsContext config\n.devscontext.yaml\n")
        gitignore_updated = True

    # Success message
    click.echo()
    click.echo(_success(f"Created {config_path}"))
    if gitignore_updated:
        click.echo(_success("Added .devscontext.yaml to .gitignore"))

    click.echo()
    click.echo(click.style("Next steps:", bold=True))
    if jira_enabled:
        click.echo("  export JIRA_EMAIL='your-email@company.com'")
        click.echo("  export JIRA_API_TOKEN='your-api-token'")
    if fireflies_enabled:
        click.echo("  export FIREFLIES_API_KEY='your-api-key'")
    click.echo("  export ANTHROPIC_API_KEY='your-api-key'")
    click.echo()
    click.echo("  devscontext test --task YOUR-123")


@cli.command()
@click.option("--task", "-t", default=None, help="Jira ticket ID (e.g., PROJ-123)")
@click.pass_context
def test(ctx: click.Context, task: str | None) -> None:
    """Test connection to configured adapters."""
    import asyncio

    from devscontext.config import load_devscontext_config
    from devscontext.core import DevsContextCore

    verbose = ctx.obj.get("verbose", False)

    try:
        config = load_devscontext_config()
    except FileNotFoundError:
        click.echo(_error("No .devscontext.yaml found. Run 'devscontext init' first."))
        sys.exit(1)

    click.echo()
    click.echo(click.style("Connection Status", bold=True))
    click.echo()

    core = DevsContextCore(config)

    async def run_health_checks() -> dict[str, bool]:
        return await core.health_check()

    results = asyncio.run(run_health_checks())
    healthy_count = sum(1 for h in results.values() if h)

    for adapter, healthy in results.items():
        if healthy:
            click.echo("  " + _success(adapter))
        else:
            click.echo("  " + _error(f"{adapter} (check credentials)"))

    click.echo()

    if not task:
        click.echo(_info("Use --task PROJ-123 to test fetching context"))
        return

    if healthy_count == 0:
        click.echo(_error("No healthy adapters. Fix connections before testing."))
        sys.exit(1)

    click.echo(click.style(f"Fetching context for {task}...", bold=True))
    click.echo()

    start_time = time.monotonic()

    async def fetch_context() -> tuple[str, list[str]]:
        result = await core.get_task_context(task)
        return result.synthesized, result.sources_used

    try:
        output, sources = asyncio.run(fetch_context())
        duration = time.monotonic() - start_time

        click.echo(output)
        click.echo()
        click.echo(
            click.style(
                f"Fetched from {len(sources)} source(s) and synthesized in {duration:.1f}s",
                fg="cyan",
            )
        )
    except Exception as e:
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        click.echo(_error(f"Failed: {e}"), err=True)
        sys.exit(1)


@cli.command()
@click.option("--demo", is_flag=True, help="Run in demo mode with sample data (no config needed)")
@click.pass_context
def serve(ctx: click.Context, demo: bool) -> None:
    """Start the MCP server (stdio transport).

    Use --demo to run without configuration. The server will respond
    to any ticket ID with sample context for a payment webhook task.

    \b
    Examples:
        devscontext serve              # Normal mode (requires config)
        devscontext serve --demo       # Demo mode (no config needed)

    \b
    Connect to Claude Code:
        claude mcp add devscontext -- devscontext serve
        claude mcp add devscontext-demo -- devscontext serve --demo
    """
    # Print startup message to stderr (stdout is for MCP protocol)
    mode = " (demo mode)" if demo else ""
    click.echo(
        click.style("DevsContext", bold=True) + f" MCP server running{mode}",
        err=True,
    )
    click.echo(
        "Tools: get_task_context, search_context, get_standards",
        err=True,
    )
    if demo:
        click.echo(
            "Demo: Returns sample context for PROJ-123 (payment webhooks)",
            err=True,
        )
    click.echo(err=True)

    from devscontext.server import main as server_main

    server_main(demo_mode=demo)


# =============================================================================
# DEMO COMMAND
# =============================================================================


@cli.command()
def demo() -> None:
    """Run demo mode - shows synthesized output from sample data.

    No configuration or API keys required. Uses realistic sample data
    for a payments webhook retry task (PROJ-123).

    This is the fastest way to see what DevsContext produces.

    \b
    Example:
        devscontext demo

    \b
    To try the full MCP server in demo mode:
        devscontext serve --demo
        claude mcp add devscontext-demo -- devscontext serve --demo
    """
    import asyncio

    from devscontext.core import DevsContextCore

    click.echo()
    click.echo(click.style("DevsContext Demo", bold=True))
    click.echo("=" * 60)
    click.echo()
    click.echo(
        "Sample task: "
        + click.style("PROJ-123", fg="cyan")
        + " — Add retry logic to payment webhook handler"
    )
    click.echo()
    click.echo("-" * 60)
    click.echo()

    async def run_demo() -> str:
        core = DevsContextCore(demo_mode=True)
        result = await core.get_task_context("PROJ-123")
        return result.synthesized

    try:
        output = asyncio.run(run_demo())
        click.echo(output)
        click.echo()
        click.echo("-" * 60)
        click.echo()
        click.echo(_info("This is what DevsContext synthesizes from Jira, meetings, and docs."))
        click.echo()
        click.echo("Next steps:")
        click.echo("  1. " + click.style("devscontext init", fg="green") + " — Configure sources")
        click.echo("  2. " + click.style("devscontext serve", fg="green") + " — Start MCP server")
        click.echo("  3. " + click.style("claude mcp add devscontext", fg="green"))
        click.echo()
    except Exception as e:
        click.echo(_error(f"Demo failed: {e}"), err=True)
        sys.exit(1)


# =============================================================================
# RAG INDEXING COMMAND
# =============================================================================


@cli.command("index-docs")
@click.option("--rebuild", is_flag=True, help="Clear and rebuild the entire index")
@click.option("--status", "show_status", is_flag=True, help="Show index statistics only")
@click.pass_context
def index_docs(ctx: click.Context, rebuild: bool, show_status: bool) -> None:
    """Build embedding index for local documentation.

    Creates vector embeddings for all markdown documents in the configured
    doc paths, enabling semantic search for better doc matching.

    This command requires RAG to be configured in .devscontext.yaml:

        \b
        sources:
          docs:
            rag:
              enabled: true
              embedding_provider: local
              embedding_model: all-MiniLM-L6-v2

    Requires: pip install devscontext[rag]
    """
    import asyncio

    from devscontext.adapters.local_docs import LocalDocsAdapter
    from devscontext.config import load_devscontext_config

    verbose = ctx.obj.get("verbose", False)

    try:
        config = load_devscontext_config()
    except FileNotFoundError:
        click.echo(_error("No .devscontext.yaml found. Run 'devscontext init' first."))
        sys.exit(1)

    if not config.sources.docs.rag:
        click.echo(_error("RAG not configured in .devscontext.yaml"))
        click.echo()
        click.echo("Add the following to your config:")
        click.echo()
        click.echo("  sources:")
        click.echo("    docs:")
        click.echo("      rag:")
        click.echo("        enabled: true")
        click.echo("        embedding_provider: local")
        sys.exit(1)

    # Check if RAG dependencies are available
    try:
        from devscontext.rag import is_rag_available

        if not is_rag_available():
            click.echo(_error("RAG dependencies not installed"))
            click.echo()
            click.echo("Install with: pip install devscontext[rag]")
            sys.exit(1)
    except ImportError:
        click.echo(_error("RAG module not available"))
        sys.exit(1)

    # Status only mode
    if show_status:
        from devscontext.rag import DocumentIndex

        index = DocumentIndex(config.sources.docs.rag.index_path)

        click.echo()
        click.echo(click.style("RAG Index Status", bold=True))
        click.echo()

        if not index.exists():
            click.echo(_error("Index does not exist"))
            click.echo(_info("Run 'devscontext index-docs' to build it"))
            return

        index.load()
        stats = index.get_stats()

        click.echo(f"  Index path:    {stats['index_path']}")
        click.echo(f"  Model:         {stats['model']}")
        click.echo(f"  Dimension:     {stats['dimension']}")
        click.echo(f"  Sections:      {stats['section_count']}")
        if stats["indexed_at"]:
            click.echo(f"  Indexed at:    {stats['indexed_at']}")

        if stats.get("doc_types"):
            click.echo()
            click.echo("  Document types:")
            for doc_type, count in stats["doc_types"].items():
                click.echo(f"    {doc_type}: {count}")

        return

    # Build/rebuild index
    click.echo()
    click.echo(click.style("Building RAG Index", bold=True))
    click.echo()

    if rebuild:
        click.echo(_info("Rebuild mode - clearing existing index"))

    click.echo(_info(f"Model: {config.sources.docs.rag.embedding_model}"))
    click.echo(_info(f"Doc paths: {', '.join(config.sources.docs.paths)}"))
    click.echo()

    adapter = LocalDocsAdapter(config.sources.docs)

    async def build_index() -> dict[str, Any]:
        return await adapter.index_documents(rebuild=rebuild)

    try:
        start_time = time.monotonic()
        result = asyncio.run(build_index())
        duration = time.monotonic() - start_time

        if result["status"] == "no_docs":
            click.echo(_error("No documents found in configured paths"))
            sys.exit(1)

        click.echo(_success(f"Indexed {result['sections_indexed']} sections in {duration:.1f}s"))
        click.echo()
        click.echo(f"  Files scanned: {result['files_scanned']}")
        click.echo(f"  Dimension:     {result['dimension']}")
        click.echo(f"  Index path:    {result['index_path']}")

    except ImportError as e:
        click.echo(_error(f"Missing dependency: {e}"))
        click.echo()
        click.echo("Install with: pip install devscontext[rag]")
        sys.exit(1)
    except Exception as e:
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        click.echo(_error(f"Indexing failed: {e}"), err=True)
        sys.exit(1)


# =============================================================================
# AGENT COMMANDS
# =============================================================================


@cli.group()
@click.pass_context
def agent(ctx: click.Context) -> None:
    """Manage the pre-processing agent.

    The agent watches Jira for tickets in a target status (e.g., "Ready for
    Development") and pre-builds rich context before anyone picks them up.

    Commands:
        start: Run polling agent in foreground
        run-once: Single poll cycle, then exit
        status: Show pre-built context stats
        process: Manually process a specific ticket
    """
    pass


@agent.command()
@click.pass_context
def start(ctx: click.Context) -> None:
    """Start the polling agent in foreground.

    Polls Jira periodically for tickets in the target status and processes
    them through the preprocessing pipeline. Press Ctrl+C to stop.
    """
    import asyncio
    import signal

    from devscontext.agents import JiraWatcher, PreprocessingPipeline
    from devscontext.config import load_devscontext_config
    from devscontext.storage import PrebuiltContextStorage

    verbose = ctx.obj.get("verbose", False)

    try:
        config = load_devscontext_config()
    except FileNotFoundError:
        click.echo(_error("No .devscontext.yaml found. Run 'devscontext init' first."))
        sys.exit(1)

    if not config.agents.preprocessor.enabled:
        click.echo(_error("Preprocessor agent not enabled in config."))
        click.echo(_info("Set agents.preprocessor.enabled: true in .devscontext.yaml"))
        sys.exit(1)

    if not config.sources.jira.enabled:
        click.echo(_error("Jira adapter not enabled. Agent requires Jira."))
        sys.exit(1)

    click.echo()
    click.echo(click.style("DevsContext Agent", bold=True))
    click.echo()
    click.echo(
        _info(f"Polling every {config.agents.preprocessor.trigger.poll_interval_minutes} minutes")
    )
    click.echo(_info(f"Watching for status: {config.agents.preprocessor.jira_status}"))
    click.echo(_info(f"Project(s): {config.agents.preprocessor.jira_project}"))
    click.echo()

    async def run_agent() -> None:
        storage = PrebuiltContextStorage(config.storage.path)
        await storage.initialize()

        pipeline = PreprocessingPipeline(config, storage)
        watcher = JiraWatcher(config, pipeline)

        # Handle Ctrl+C gracefully
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, watcher.stop)

        try:
            click.echo(_success("Agent started. Press Ctrl+C to stop."))
            click.echo()
            await watcher.run()
        finally:
            await watcher.close()
            await pipeline.close()
            await storage.close()

    try:
        asyncio.run(run_agent())
    except Exception as e:
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        click.echo(_error(f"Agent error: {e}"), err=True)
        sys.exit(1)

    click.echo()
    click.echo(_success("Agent stopped."))


@agent.command("run-once")
@click.pass_context
def run_once(ctx: click.Context) -> None:
    """Single run: check for ready tickets, process, exit.

    Useful for cron jobs or CI pipelines. Performs one poll cycle,
    processes any new tickets found, and exits.
    """
    import asyncio

    from devscontext.agents import JiraWatcher, PreprocessingPipeline
    from devscontext.config import load_devscontext_config
    from devscontext.storage import PrebuiltContextStorage

    verbose = ctx.obj.get("verbose", False)

    try:
        config = load_devscontext_config()
    except FileNotFoundError:
        click.echo(_error("No .devscontext.yaml found."))
        sys.exit(1)

    if not config.agents.preprocessor.enabled:
        click.echo(_error("Preprocessor agent not enabled in config."))
        sys.exit(1)

    click.echo(click.style("DevsContext Agent - Single Run", bold=True))
    click.echo()

    async def run_single() -> int:
        storage = PrebuiltContextStorage(config.storage.path)
        await storage.initialize()

        pipeline = PreprocessingPipeline(config, storage)
        watcher = JiraWatcher(config, pipeline)

        try:
            processed = await watcher.run_once()
            return processed
        finally:
            await watcher.close()
            await pipeline.close()
            await storage.close()

    try:
        processed = asyncio.run(run_single())
        click.echo()
        click.echo(_success(f"Processed {processed} ticket(s)."))
    except Exception as e:
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        click.echo(_error(f"Error: {e}"), err=True)
        sys.exit(1)


@agent.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show pre-built context stats.

    Displays statistics about stored pre-built context including
    total count, active count, average quality, and last build time.
    """
    import asyncio

    from devscontext.config import load_devscontext_config
    from devscontext.storage import PrebuiltContextStorage

    try:
        config = load_devscontext_config()
    except FileNotFoundError:
        click.echo(_error("No .devscontext.yaml found."))
        sys.exit(1)

    async def get_status() -> dict[str, Any]:
        storage = PrebuiltContextStorage(config.storage.path)
        try:
            await storage.initialize()
            stats = await storage.get_stats()
            return stats
        finally:
            await storage.close()

    try:
        stats = asyncio.run(get_status())
    except Exception as e:
        click.echo(_error(f"Could not read storage: {e}"))
        sys.exit(1)

    click.echo()
    click.echo(click.style("Pre-built Context Storage", bold=True))
    click.echo()
    click.echo(f"  Total contexts:       {stats['total']}")
    click.echo(f"  Active (not expired): {stats['active']}")
    click.echo(f"  Expired:              {stats['expired']}")

    if stats["avg_quality"] > 0:
        click.echo(f"  Average quality:      {stats['avg_quality']:.1%}")

    if stats["last_build"]:
        click.echo(f"  Last build:           {stats['last_build']}")
    else:
        click.echo("  Last build:           (none)")

    click.echo()
    click.echo(_info(f"Storage path: {config.storage.path}"))


@agent.command()
@click.argument("task_id")
@click.pass_context
def process(ctx: click.Context, task_id: str) -> None:
    """Manually trigger pre-processing for a specific ticket.

    TASK_ID is the Jira ticket ID (e.g., PROJ-123).

    This bypasses the watcher and immediately processes the specified
    ticket through the full preprocessing pipeline.
    """
    import asyncio

    from devscontext.agents import PreprocessingPipeline
    from devscontext.config import load_devscontext_config
    from devscontext.storage import PrebuiltContextStorage

    verbose = ctx.obj.get("verbose", False)

    try:
        config = load_devscontext_config()
    except FileNotFoundError:
        click.echo(_error("No .devscontext.yaml found."))
        sys.exit(1)

    click.echo()
    click.echo(click.style(f"Processing {task_id}", bold=True))
    click.echo()

    start_time = time.monotonic()

    async def process_ticket() -> dict[str, Any]:
        storage = PrebuiltContextStorage(config.storage.path)
        await storage.initialize()

        pipeline = PreprocessingPipeline(config, storage)

        try:
            context = await pipeline.process(task_id)
            return {
                "quality_score": context.context_quality_score,
                "gaps": context.gaps,
                "sources_count": len(context.sources_used),
            }
        finally:
            await pipeline.close()
            await storage.close()

    try:
        result = asyncio.run(process_ticket())
        duration = time.monotonic() - start_time

        click.echo(_success(f"Processed in {duration:.1f}s"))
        click.echo()
        click.echo(f"  Quality score: {result['quality_score']:.1%}")
        click.echo(f"  Sources used:  {result['sources_count']}")

        if result["gaps"]:
            click.echo()
            click.echo(click.style("Identified gaps:", fg="yellow"))
            for gap in result["gaps"]:
                click.echo(f"  - {gap}")
        else:
            click.echo()
            click.echo(_success("No gaps identified - context is complete!"))

    except Exception as e:
        if verbose:
            import traceback

            click.echo(traceback.format_exc(), err=True)
        click.echo(_error(f"Failed to process: {e}"), err=True)
        sys.exit(1)


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
