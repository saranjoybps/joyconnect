"""MCP server built from the connector registry (in-process only in this phase).

Uses the official `mcp` SDK (2.x). FastMCP was renamed MCPServer in 2.x and infers
schemas from Python signatures; our tools are schema-first, so we use the SDK's
low-level `Server` with explicit input schemas and annotations.

Annotations are hints for MCP clients only. Policy is enforced by the caller
(`app.agent.policy`), never by these hints.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Iterable

import mcp.types as types
from mcp.server.lowlevel import Server

from app.connectors.base import ConnectorManifest, Risk, ToolDef
from app.connectors.registry import all_tools

CallTool = Callable[[str, dict[str, Any]], Awaitable[tuple[bool, Any]]]


def annotations_for(risk: Risk) -> types.ToolAnnotations:
    return types.ToolAnnotations(
        read_only_hint=risk == "read",
        destructive_hint=risk == "destructive",
        idempotent_hint=risk == "read",
        open_world_hint=True,
    )


def to_mcp_tool(tool: ToolDef) -> types.Tool:
    return types.Tool(name=tool.name, description=tool.description, input_schema=tool.parameters,
                      annotations=annotations_for(tool.risk))


def build_mcp_server(call_tool: CallTool,
                     tools: Iterable[tuple[ConnectorManifest, ToolDef]] | None = None) -> Server:
    """`call_tool` must apply the approval policy and bind the user's connection."""
    defs = {t.name: t for _, t in (tools if tools is not None else all_tools().values())}

    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[to_mcp_tool(t) for t in defs.values()])

    async def on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name not in defs:
            return types.CallToolResult(content=[types.TextContent(type="text", text="unknown tool")], is_error=True)
        ok, result = await call_tool(params.name, dict(params.arguments or {}))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, default=str))], is_error=not ok)

    return Server("connect", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
