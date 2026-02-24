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
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start the MCP server (stdio transport)."""

    # Print startup message to stderr (stdout is for MCP protocol)
    click.echo(
        click.style("DevsContext", bold=True) + " MCP server running",
        err=True,
    )
    click.echo(
        "Tools: get_task_context, search_context, get_standards",
        err=True,
    )
    click.echo(err=True)

    from devscontext.server import main as server_main

    server_main()


def main() -> None:
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
