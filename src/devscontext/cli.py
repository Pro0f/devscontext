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

    Guides the user through setting up adapters and configuration.
    Currently shows placeholder text with manual setup instructions.
    """
    click.echo("TODO: interactive setup")
    click.echo()
    click.echo("For now, copy .devscontext.yaml.example to .devscontext.yaml")
    click.echo("and configure your adapters manually.")


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
    click.echo("TODO: test connection")
    click.echo()
    if ticket:
        click.echo(f"Would test fetching context for: {ticket}")
    else:
        click.echo("Use --ticket PROJ-123 to test fetching a specific ticket.")


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
