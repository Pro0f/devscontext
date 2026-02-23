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
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from devscontext.config import load_config
from devscontext.core import ContextOrchestrator
from devscontext.logging import get_logger

logger = get_logger(__name__)

# Initialize the MCP server
server = Server("devscontext")

# Global orchestrator instance (initialized on startup)
_orchestrator: ContextOrchestrator | None = None


def get_orchestrator() -> ContextOrchestrator:
    """Get or create the global orchestrator instance.

    Lazily initializes the orchestrator on first access using
    the configuration loaded from the config file.

    Returns:
        The singleton ContextOrchestrator instance.
    """
    global _orchestrator
    if _orchestrator is None:
        config = load_config()
        _orchestrator = ContextOrchestrator(config)
        logger.info("Orchestrator initialized")
    return _orchestrator


@server.list_tools()
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
                "Get full synthesized context for a Jira ticket. "
                "Returns ticket details, comments, linked issues, related meeting discussions, "
                "and applicable documentation combined into a structured context block."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The Jira ticket ID (e.g., 'PROJ-123')",
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
                "Search across all configured sources (Jira, meeting transcripts, docs) "
                "by keyword. Returns matching content from all sources."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (keyword or phrase)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_standards",
            description=(
                "Get coding standards and guidelines from local documentation. "
                "Optionally filter by area (e.g., 'typescript', 'testing', 'api')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": "Optional area to filter (e.g., 'typescript')",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle MCP tool calls.

    Routes tool calls to the appropriate orchestrator method and formats
    the response for the MCP client.

    Args:
        name: The name of the tool to call.
        arguments: The tool arguments as a dictionary.

    Returns:
        List containing a single TextContent with the tool result.
    """
    orchestrator = get_orchestrator()
    logger.debug("Tool call received", extra={"tool": name, "arguments": arguments})

    if name == "get_task_context":
        task_id = arguments.get("task_id", "")
        refresh = arguments.get("refresh", False)

        if not task_id:
            logger.warning("get_task_context called without task_id")
            return [TextContent(type="text", text="Error: task_id is required")]

        result = await orchestrator.get_task_context(
            task_id=task_id,
            use_cache=not refresh,
        )

        logger.info(
            "get_task_context completed",
            extra={"task_id": task_id, "item_count": result["item_count"]},
        )

        response_text = f"""# Context for {result["task_id"]}

**Sources:** {", ".join(result["sources"])}
**Items found:** {result["item_count"]}

---

{result["context"]}
"""
        return [TextContent(type="text", text=response_text)]

    elif name == "search_context":
        query = arguments.get("query", "")

        if not query:
            logger.warning("search_context called without query")
            return [TextContent(type="text", text="Error: query is required")]

        result = await orchestrator.search_context(query=query)

        logger.info(
            "search_context completed",
            extra={"query": query, "result_count": result["result_count"]},
        )

        response_text = f"""# Search Results for "{query}"

**Sources searched:** {", ".join(result["sources"])}
**Results found:** {result["result_count"]}

---

{result["results"]}
"""
        return [TextContent(type="text", text=response_text)]

    elif name == "get_standards":
        area = arguments.get("area")

        result = await orchestrator.get_standards(area=area)

        logger.info("get_standards completed", extra={"area": area})

        area_text = f" ({area})" if area else ""
        response_text = f"""# Coding Standards{area_text}

{result["content"]}
"""
        return [TextContent(type="text", text=response_text)]

    else:
        logger.warning("Unknown tool called", extra={"tool": name})
        return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]


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
