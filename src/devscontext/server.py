"""MCP server for DevsContext.

This module provides the Model Context Protocol (MCP) server implementation
that exposes DevsContext functionality as MCP tools.

The server runs over stdio transport and provides the following tools:
    - get_task_context: Get synthesized context for a task
    - search_context: Search across all configured sources
    - get_standards: Get coding standards documentation

Example:
    Run as MCP server:
        devscontext serve
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from devscontext.config import load_devscontext_config
from devscontext.core import DevsContextCore
from devscontext.logging import get_logger

logger = get_logger(__name__)

# Initialize the MCP server
server = Server("devscontext")

# Global core instance (initialized on startup)
_core: DevsContextCore | None = None


def get_core() -> DevsContextCore:
    """Get or create the global DevsContextCore instance.

    Lazily initializes the core on first access using
    the configuration loaded from the config file.

    Returns:
        The singleton DevsContextCore instance.
    """
    global _core
    if _core is None:
        config = load_devscontext_config()
        _core = DevsContextCore(config)
        logger.info("DevsContextCore initialized")
    return _core


@server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
async def list_tools() -> list[Tool]:
    """List available MCP tools.

    Returns:
        List of Tool definitions for get_task_context, search_context,
        and get_standards.
    """
    return [
        Tool(
            name="get_task_context",
            description=(
                "Use this when starting work on a Jira ticket. "
                "Fetches and synthesizes everything you need: ticket requirements, "
                "acceptance criteria, discussion comments, related meeting transcripts, "
                "architecture docs, ADRs, and applicable coding standards. "
                "Call this FIRST when the user says 'work on PROJ-123' or 'start TICKET-456'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Jira ticket ID (e.g., 'PROJ-123', 'TICKET-456')",
                    },
                    "refresh": {
                        "type": "boolean",
                        "description": "Force refresh, bypassing cache",
                        "default": False,
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="search_context",
            description=(
                "Use this for freeform questions about the codebase, architecture, "
                "or past decisions. Searches across Jira tickets, meeting transcripts, "
                "and documentation. Use when the user asks questions like "
                "'how do we handle errors?', 'what was decided about webhooks?', "
                "or 'why did we choose SQS?'. Input is a natural language question."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language question or search terms",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_standards",
            description=(
                "Use this when checking coding conventions before or during implementation. "
                "Returns coding standards, style guides, and best practices from local docs. "
                "Filter by area: 'testing', 'error-handling', 'typescript', 'api', etc. "
                "Use when the user asks 'what are our testing conventions?' or "
                "'how should I handle errors?' or before writing significant code."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": (
                            "Filter by area: 'testing', 'typescript', 'error-handling', etc. "
                            "Omit to get all standards."
                        ),
                    },
                },
            },
        ),
    ]


@server.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle MCP tool calls.

    Routes tool calls to the appropriate core method and formats
    the response for the MCP client.

    Args:
        name: The name of the tool to call.
        arguments: The tool arguments as a dictionary.

    Returns:
        List containing a single TextContent with the tool result.
    """
    start_time = time.monotonic()
    core = get_core()

    logger.info(
        "Tool call received",
        extra={"tool": name, "arguments": arguments},
    )

    try:
        if name == "get_task_context":
            return await _handle_get_task_context(core, arguments, start_time)

        elif name == "search_context":
            return await _handle_search_context(core, arguments, start_time)

        elif name == "get_standards":
            return await _handle_get_standards(core, arguments, start_time)

        else:
            logger.warning("Unknown tool called", extra={"tool": name})
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.exception(
            "Tool call failed",
            extra={"tool": name, "error": str(e), "duration_ms": duration_ms},
        )
        return [
            TextContent(
                type="text",
                text=f"Error: An unexpected error occurred while processing '{name}': {e}",
            )
        ]


async def _handle_get_task_context(
    core: DevsContextCore,
    arguments: dict[str, Any],
    start_time: float,
) -> list[TextContent]:
    """Handle the get_task_context tool call.

    Args:
        core: The DevsContextCore instance.
        arguments: Tool arguments.
        start_time: When the request started for duration logging.

    Returns:
        List containing TextContent with the synthesized context.
    """
    task_id = arguments.get("task_id", "")
    refresh = arguments.get("refresh", False)

    if not task_id:
        logger.warning("get_task_context called without task_id")
        return [TextContent(type="text", text="Error: task_id is required")]

    try:
        result = await core.get_task_context(
            task_id=task_id,
            use_cache=not refresh,
        )

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "get_task_context completed",
            extra={
                "task_id": task_id,
                "source_count": len(result.sources_used),
                "cached": result.cached,
                "duration_ms": duration_ms,
            },
        )

        # Return the synthesized markdown directly
        return [TextContent(type="text", text=result.synthesized)]

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.exception(
            "get_task_context failed",
            extra={"task_id": task_id, "error": str(e), "duration_ms": duration_ms},
        )
        return [
            TextContent(
                type="text",
                text=f"Error fetching context for {task_id}: {e}\n\n"
                f"Please check that your Jira and Fireflies credentials are configured correctly.",
            )
        ]


async def _handle_search_context(
    core: DevsContextCore,
    arguments: dict[str, Any],
    start_time: float,
) -> list[TextContent]:
    """Handle the search_context tool call.

    Args:
        core: The DevsContextCore instance.
        arguments: Tool arguments.
        start_time: When the request started for duration logging.

    Returns:
        List containing TextContent with search results.
    """
    query = arguments.get("query", "")

    if not query:
        logger.warning("search_context called without query")
        return [TextContent(type="text", text="Error: query is required")]

    try:
        result = await core.search_context(query=query)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "search_context completed",
            extra={
                "query": query,
                "result_count": result["result_count"],
                "duration_ms": duration_ms,
            },
        )

        sources = result.get("sources", [])
        sources_str = ", ".join(sources) if isinstance(sources, list) else str(sources)

        response_text = f"""# Search Results for "{query}"

**Sources searched:** {sources_str}
**Results found:** {result["result_count"]}

---

{result["results"]}
"""
        return [TextContent(type="text", text=response_text)]

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.exception(
            "search_context failed",
            extra={"query": query, "error": str(e), "duration_ms": duration_ms},
        )
        return [
            TextContent(
                type="text",
                text=f"Error searching for '{query}': {e}",
            )
        ]


async def _handle_get_standards(
    core: DevsContextCore,
    arguments: dict[str, Any],
    start_time: float,
) -> list[TextContent]:
    """Handle the get_standards tool call.

    Args:
        core: The DevsContextCore instance.
        arguments: Tool arguments.
        start_time: When the request started for duration logging.

    Returns:
        List containing TextContent with standards content.
    """
    area = arguments.get("area")

    try:
        result = await core.get_standards(area=area)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "get_standards completed",
            extra={"area": area, "duration_ms": duration_ms},
        )

        area_text = f" ({area})" if area else ""
        response_text = f"""# Coding Standards{area_text}

{result["content"]}
"""
        return [TextContent(type="text", text=response_text)]

    except Exception as e:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.exception(
            "get_standards failed",
            extra={"area": area, "error": str(e), "duration_ms": duration_ms},
        )
        return [
            TextContent(
                type="text",
                text=f"Error fetching standards: {e}",
            )
        ]


async def run_server() -> None:
    """Run the MCP server over stdio transport.

    Sets up the stdio transport and runs the server until interrupted.
    """
    logger.info("Starting MCP server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point for the MCP server.

    Configures logging and runs the async server.
    """
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
