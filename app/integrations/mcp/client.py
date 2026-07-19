"""Synchronous one-shot client over the official MCP stdio transport."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.integrations.mcp.errors import (
    McpClientError,
    McpProtocolError,
    McpResultInvalidError,
    McpServerUnavailableError,
    McpSyncBridgeError,
    McpTimeoutError,
    McpToolFailedError,
    McpToolSchemaMismatchError,
)
from app.integrations.mcp.models import McpServerConfig, McpToolCallResult


logger = logging.getLogger(__name__)


class OneShotStdioMcpClient:
    """Launch, initialize, call one known tool, and close one MCP server."""

    def call_tool(
        self,
        config: McpServerConfig,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        expected_input_schema: Mapping[str, Any],
    ) -> McpToolCallResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise McpSyncBridgeError(
                "The synchronous MCP client cannot run inside an active event loop."
            )

        logger.info(
            "MCP call started server_id=%s tool_name=%s stage=session",
            config.server_id,
            tool_name,
        )
        try:
            result = asyncio.run(
                self._call_tool(
                    config,
                    tool_name=tool_name,
                    arguments=dict(arguments),
                    expected_input_schema=dict(expected_input_schema),
                )
            )
            logger.info(
                "MCP call completed server_id=%s tool_name=%s stage=close",
                config.server_id,
                tool_name,
            )
            return result
        except McpClientError as exc:
            _log_failure(config, tool_name, exc.code)
            raise
        except TimeoutError as exc:
            _log_failure(config, tool_name, McpTimeoutError.code)
            raise McpTimeoutError("The MCP call exceeded its time limit.") from exc
        except OSError as exc:
            _log_failure(config, tool_name, McpServerUnavailableError.code)
            raise McpServerUnavailableError(
                "The MCP server could not be started."
            ) from exc
        except Exception as exc:
            nested_client_error = _find_exception(exc, McpClientError)
            if nested_client_error is not None:
                _log_failure(config, tool_name, nested_client_error.code)
                raise nested_client_error from exc
            if _contains_exception(exc, TimeoutError):
                _log_failure(config, tool_name, McpTimeoutError.code)
                raise McpTimeoutError(
                    "The MCP call exceeded its time limit."
                ) from exc
            if _contains_exception(exc, OSError):
                _log_failure(config, tool_name, McpServerUnavailableError.code)
                raise McpServerUnavailableError(
                    "The MCP server could not be started."
                ) from exc
            try:
                import anyio

                unavailable_types = (
                    anyio.EndOfStream,
                    anyio.BrokenResourceError,
                    anyio.ClosedResourceError,
                )
            except ImportError:  # pragma: no cover - dependency of the MCP SDK
                unavailable_types = ()
            if unavailable_types and _contains_exception(exc, unavailable_types):
                _log_failure(config, tool_name, McpServerUnavailableError.code)
                raise McpServerUnavailableError(
                    "The MCP server exited before completing the call."
                ) from exc
            _log_failure(config, tool_name, McpProtocolError.code)
            raise McpProtocolError(
                "The MCP session ended without a valid protocol result."
            ) from exc

    async def _call_tool(
        self,
        config: McpServerConfig,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        expected_input_schema: dict[str, Any],
    ) -> McpToolCallResult:
        parameters = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            cwd=config.cwd,
        )
        read_timeout = timedelta(seconds=config.timeout_seconds)

        timeout_context = asyncio.timeout(config.timeout_seconds)
        try:
            async with timeout_context:
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=read_timeout,
                    ) as session:
                        try:
                            await session.initialize()
                        except Exception as exc:
                            raise McpServerUnavailableError(
                                "The MCP server exited during initialization."
                            ) from exc
                        return await self._call_initialized_tool(
                            session,
                            config=config,
                            tool_name=tool_name,
                            arguments=arguments,
                            expected_input_schema=expected_input_schema,
                            read_timeout=read_timeout,
                        )
        except BaseException as exc:
            if timeout_context.expired():
                raise McpTimeoutError(
                    "The MCP call exceeded its time limit."
                ) from exc
            raise

    async def _call_initialized_tool(
        self,
        session: ClientSession,
        *,
        config: McpServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
        expected_input_schema: dict[str, Any],
        read_timeout: timedelta,
    ) -> McpToolCallResult:
        listed = await session.list_tools()
        matching = tuple(tool for tool in listed.tools if tool.name == tool_name)
        if len(matching) != 1:
            raise McpToolSchemaMismatchError(
                "The expected MCP tool is not exposed exactly once."
            )
        if matching[0].inputSchema != expected_input_schema:
            raise McpToolSchemaMismatchError(
                "The MCP tool input schema does not match the adapter contract."
            )

        called = await session.call_tool(
            tool_name,
            arguments=arguments,
            read_timeout_seconds=read_timeout,
        )
        if called.isError:
            raise McpToolFailedError(
                "The MCP tool reported a safe execution failure."
            )
        if not isinstance(called.structuredContent, dict):
            raise McpResultInvalidError(
                "The MCP tool did not return structured content."
            )
        return McpToolCallResult(
            server_id=config.server_id,
            tool_name=tool_name,
            structured_content=called.structuredContent,
            is_error=called.isError,
        )


def call_tool_once(
    config: McpServerConfig,
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    expected_input_schema: Mapping[str, Any],
) -> McpToolCallResult:
    """Convenience façade for callers that do not need to retain a client."""

    return OneShotStdioMcpClient().call_tool(
        config,
        tool_name=tool_name,
        arguments=arguments,
        expected_input_schema=expected_input_schema,
    )


def _contains_exception(
    error: BaseException,
    error_type: type[BaseException] | tuple[type[BaseException], ...],
) -> bool:
    if isinstance(error, error_type):
        return True
    if isinstance(error, BaseExceptionGroup):
        return any(
            _contains_exception(child, error_type) for child in error.exceptions
        )
    return False


def _log_failure(
    config: McpServerConfig,
    tool_name: str,
    error_code: str,
) -> None:
    logger.warning(
        "MCP call failed server_id=%s tool_name=%s stage=session error_code=%s",
        config.server_id,
        tool_name,
        error_code,
    )


def _find_exception(
    error: BaseException,
    error_type: type[McpClientError],
) -> McpClientError | None:
    if isinstance(error, error_type):
        return error
    if isinstance(error, BaseExceptionGroup):
        for child in error.exceptions:
            found = _find_exception(child, error_type)
            if found is not None:
                return found
    return None
