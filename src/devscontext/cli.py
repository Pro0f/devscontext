"""CLI entry point for DevsContext."""

import argparse
import sys


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="devscontext",
        description="MCP server for aggregating development context",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Server command (default)
    subparsers.add_parser(
        "serve",
        help="Start the MCP server (default)",
    )

    # Version command
    subparsers.add_parser(
        "version",
        help="Show version information",
    )

    args = parser.parse_args()

    if args.command == "version" or "--version" in sys.argv or "-v" in sys.argv:
        from devscontext import __version__

        print(f"devscontext {__version__}")
        return

    # Default to serve command
    from devscontext.server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
