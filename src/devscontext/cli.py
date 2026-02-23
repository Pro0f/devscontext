"""CLI entry point for DevsContext."""

import click

from devscontext import __version__


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="devscontext")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """DevsContext - MCP server for AI coding context.

    Provides synthesized engineering context from Jira, meeting transcripts,
    and local documentation to AI coding assistants.
    """
    if ctx.invoked_subcommand is None:
        # Default to serve if no command specified
        ctx.invoke(serve)


@cli.command()
def init() -> None:
    """Create .devscontext.yaml configuration interactively."""
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
    """Test connection to configured adapters."""
    click.echo("TODO: test connection")
    click.echo()
    if ticket:
        click.echo(f"Would test fetching context for: {ticket}")
    else:
        click.echo("Use --ticket PROJ-123 to test fetching a specific ticket.")


@cli.command()
def serve() -> None:
    """Start the MCP server (stdio transport)."""
    from devscontext.server import main as server_main

    server_main()


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
