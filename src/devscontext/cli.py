"""CLI entry point for DevsContext.

This module provides the command-line interface for DevsContext,
including commands for initialization, testing, and running the server.

Commands:
    init: Create configuration file interactively
    test: Test connection to configured adapters
    serve: Start the MCP server (default)

Example:
    # Start the server
    devscontext serve

    # Test with a specific ticket
    devscontext test --ticket PROJ-123
"""

from __future__ import annotations

import click

from devscontext import __version__


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="devscontext")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """DevsContext - MCP server for AI coding context.

    Provides synthesized engineering context from Jira, meeting transcripts,
    and local documentation to AI coding assistants.

    If no command is specified, defaults to 'serve'.
    """
    if ctx.invoked_subcommand is None:
        # Default to serve if no command specified
        ctx.invoke(serve)


@cli.command()
def init() -> None:
    """Create .devscontext.yaml configuration interactively.

    Creates a starter configuration file with common defaults.
    """
    from pathlib import Path

    config_path = Path(".devscontext.yaml")

    if config_path.exists():
        click.echo(f"Config file already exists: {config_path}")
        if not click.confirm("Overwrite?", default=False):
            click.echo("Aborted.")
            return

    config_content = """\
# DevsContext Configuration
# See https://github.com/anthropics/devscontext for documentation

adapters:
  jira:
    enabled: true
    base_url: "https://your-company.atlassian.net"
    email: "${JIRA_EMAIL}"
    api_token: "${JIRA_API_TOKEN}"

  fireflies:
    enabled: false
    api_key: "${FIREFLIES_API_KEY}"

  local_docs:
    enabled: true
    paths:
      - "./docs"
      - "./CLAUDE.md"

synthesis:
  provider: "anthropic"
  model: "claude-3-haiku-20240307"

cache:
  ttl_seconds: 300
  max_size: 100
"""

    config_path.write_text(config_content)
    click.echo(f"Created {config_path}")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Edit .devscontext.yaml with your Jira URL")
    click.echo("  2. Set environment variables:")
    click.echo("     export JIRA_EMAIL='your-email@company.com'")
    click.echo("     export JIRA_API_TOKEN='your-api-token'")
    click.echo("  3. Test: devscontext test --ticket YOUR-123")


@cli.command()
@click.option(
    "--ticket",
    "-t",
    default=None,
    help="Jira ticket ID to test with (e.g., PROJ-123)",
)
def test(ticket: str | None) -> None:
    """Test connection to configured adapters.

    Verifies that all enabled adapters can connect to their respective
    services. Optionally tests fetching context for a specific ticket.
    """
    import asyncio

    from devscontext.config import load_devscontext_config
    from devscontext.core import DevsContextCore

    try:
        config = load_devscontext_config()
    except FileNotFoundError:
        click.echo("No .devscontext.yaml found. Run 'devscontext init' first.")
        return

    click.echo("Testing adapter connections...")
    click.echo()

    core = DevsContextCore(config)

    async def run_health_checks() -> dict[str, bool]:
        return await core.health_check()

    results = asyncio.run(run_health_checks())

    for adapter, healthy in results.items():
        status = click.style("✓", fg="green") if healthy else click.style("✗", fg="red")
        click.echo(f"  {status} {adapter}")

    click.echo()

    if ticket:
        click.echo(f"Fetching context for {ticket}...")

        async def fetch_context() -> str:
            result = await core.get_task_context(ticket)
            return result.synthesized

        try:
            output = asyncio.run(fetch_context())
            click.echo()
            click.echo(output)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
    else:
        click.echo("Use --ticket PROJ-123 to test fetching a ticket.")


@cli.command()
def serve() -> None:
    """Start the MCP server (stdio transport).

    Runs the Model Context Protocol server over stdio, allowing
    AI coding assistants to connect and request context.
    """
    from devscontext.server import main as server_main

    server_main()


def main() -> None:
    """Main entry point for the CLI.

    Invokes the click command group.
    """
    cli()


if __name__ == "__main__":
    main()
