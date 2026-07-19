"""Small real stdio MCP server for client lifecycle tests."""

from __future__ import annotations

from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP


class EchoResult(BaseModel):
    value: str


server = FastMCP("lifeops-test-echo", log_level="ERROR")


@server.tool(name="echo", structured_output=True)
def echo(value: str) -> EchoResult:
    return EchoResult(value=value)


if __name__ == "__main__":
    server.run(transport="stdio")
