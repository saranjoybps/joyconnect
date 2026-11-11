import json

from mcp import Client

from app.connectors.registry import all_tools
from app.mcp.server import build_mcp_server


async def test_mcp_lists_registry_tools_with_annotations():
    async def call(name, args):
        return True, {}

    async with Client(build_mcp_server(call)) as client:
        result = await client.list_tools()
    tools = {t.name: t for t in result.tools}
    assert set(tools) == set(all_tools())
    read = tools["notion__search"]
    assert read.annotations.read_only_hint is True and read.annotations.open_world_hint is True
    write = tools["slack__post_message"]
    assert write.annotations.read_only_hint is False and write.annotations.destructive_hint is False
    assert write.input_schema["additionalProperties"] is False


async def test_mcp_call_routes_through_callback():
    seen = []

    async def call(name, args):
        seen.append((name, args))
        return (name != "slack__post_message"), {"echo": args}

    async with Client(build_mcp_server(call)) as client:
        ok = await client.call_tool("notion__search", {"query": "x"})
        bad = await client.call_tool("slack__post_message", {"channel": "C", "text": "t"})
    assert seen[0] == ("notion__search", {"query": "x"})
    assert ok.is_error is False and json.loads(ok.content[0].text) == {"echo": {"query": "x"}}
    assert bad.is_error is True
