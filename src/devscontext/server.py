"""MCP server for DevsContext."""

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from devscontext.config import load_config
from devscontext.core import ContextOrchestrator

# Initialize the MCP server
server = Server("devscontext")

# Global orchestrator instance (initialized on startup)
_orchestrator: ContextOrchestrator | None = None


def get_orchestrator() -> ContextOrchestrator:
    """Get the global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        config = load_config()
        _orchestrator = ContextOrchestrator(config)
    return _orchestrator


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="get_task_context",
            description=(
                "Get aggregated context for a development task from multiple sources "
                "(Jira, meeting transcripts, local documentation). "
                "Provide a task ID (e.g., Jira ticket like 'PROJ-123') to retrieve "
                "relevant context including ticket details, related meeting discussions, "
                "and applicable documentation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": (
                            "The task identifier (e.g., Jira ticket ID like 'PROJ-123', "
                            "or any string to search for in meeting transcripts and docs)"
                        ),
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
            name="health_check",
            description="Check the health status of all configured context adapters.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    orchestrator = get_orchestrator()

    if name == "get_task_context":
        task_id = arguments.get("task_id", "")
        refresh = arguments.get("refresh", False)

        if not task_id:
            return [TextContent(type="text", text="Error: task_id is required")]

        result = await orchestrator.get_task_context(
            task_id=task_id,
            use_cache=not refresh,
        )

        # Format the response
        response_text = f"""# Context for {result['task_id']}

**Sources:** {', '.join(result['sources'])}
**Items found:** {result['item_count']}

---

{result['context']}
"""
        return [TextContent(type="text", text=response_text)]

    elif name == "health_check":
        result = await orchestrator.health_check()

        status = "healthy" if result["healthy"] else "unhealthy"
        adapter_status = "\n".join(
            f"  - {name}: {'OK' if healthy else 'FAIL'}"
            for name, healthy in result["adapters"].items()
        )

        response_text = f"""# DevsContext Health Check

**Status:** {status}

**Adapters:**
{adapter_status if adapter_status else "  (no adapters configured)"}
"""
        return [TextContent(type="text", text=response_text)]

    else:
        return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]


async def run_server() -> None:
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point for the MCP server."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
