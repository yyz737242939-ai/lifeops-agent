"""MCP fixture tools for timeout, tool-error, and invalid-result tests."""

from __future__ import annotations

import asyncio
import argparse
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel


class EchoResult(BaseModel):
    value: str


class PidResult(BaseModel):
    pid: int


server = FastMCP("lifeops-test-failures", log_level="ERROR")


@server.tool(name="slow", structured_output=True)
async def slow(value: str) -> EchoResult:
    await asyncio.sleep(5)
    return EchoResult(value=value)


@server.tool(name="fail", structured_output=False)
def fail(value: str) -> str:
    del value
    raise RuntimeError("fixture provider secret must stay on stderr")


@server.tool(name="plain", structured_output=False)
def plain(value: str) -> str:
    return value


@server.tool(name="get_pid", structured_output=True)
def get_pid() -> PidResult:
    return PidResult(pid=os.getpid())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pid-file", type=Path)
    arguments, _ = parser.parse_known_args()
    if arguments.pid_file is not None:
        arguments.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    server.run(transport="stdio")
