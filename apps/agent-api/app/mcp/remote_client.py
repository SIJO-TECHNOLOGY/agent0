"""Remote MCP client over Streamable HTTP transport.

Wraps the official `mcp` Python SDK so the Agent API speaks MCP
without hand-rolling JSON-RPC. The client owns an MCP session for
the lifetime of the FastAPI app: `connect()` opens the transport
and initializes the session; `aclose()` tears them down.

Server-specific concerns (BoondManager, Spring AI) live behind the
MCP server, not here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, TextContent, Tool

from app.mcp.client import McpClient, McpToolError, McpTransientError
from app.mcp.result_normalizer import coerce_records as _coerce_records
from app.models.tools import McpTool

logger = logging.getLogger(__name__)


_TRANSIENT_EXC = (
    TimeoutError,
    ConnectionError,
    httpx.TransportError,
    httpx.TimeoutException,
    anyio.EndOfStream,
    anyio.ClosedResourceError,
)


async def _best_effort_close(stack: AsyncExitStack) -> None:
    """Close an exit stack swallowing any secondary failures.

    Used during failed connect() teardown so the original transport
    failure is what propagates, not a noisy cleanup error.
    """
    try:
        await stack.aclose()
    except BaseException:  # noqa: BLE001 — secondary cleanup only
        logger.exception("remote_mcp.cleanup_after_failed_connect_failed")


class RemoteMcpClient(McpClient):
    """MCP client backed by the official SDK's Streamable HTTP transport."""

    def __init__(self, url: str, *, timeout_seconds: float = 15.0) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._ready = False

    @property
    def url(self) -> str:
        return self._url

    async def connect(self) -> None:
        """Open the Streamable HTTP transport and initialize the MCP session.

        Idempotent: a second call while already connected is a no-op.
        """
        if self._session is not None or self._ready:
            return

        async with self._open_session():
            pass
        self._ready = True
        logger.info("remote_mcp.connected", extra={"url": self._url})

    @asynccontextmanager
    async def _open_session(self):
        """Open a short-lived MCP session in the current async task.

        The MCP SDK's Streamable HTTP transport owns anyio cancel scopes
        that must be closed by the same task that opened them. Keeping a
        transport alive across FastAPI request tasks can leave the app in
        a half-shutdown state when Spring terminates an MCP session, so
        normal operations use operation-scoped sessions.
        """
        stack = AsyncExitStack()
        try:
            transport = await stack.enter_async_context(
                streamablehttp_client(self._url, timeout=self._timeout_seconds)
            )
            read_stream, write_stream, *_ = transport
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
        except asyncio.CancelledError as exc:
            await _best_effort_close(stack)
            raise McpTransientError(
                f"MCP session initialization was cancelled for {self._url}: {exc}"
            ) from exc
        except _TRANSIENT_EXC as exc:
            await _best_effort_close(stack)
            raise McpTransientError(
                f"failed to connect to MCP server at {self._url}: {exc}"
            ) from exc
        except Exception:
            await _best_effort_close(stack)
            raise

        try:
            yield session
        finally:
            await _best_effort_close(stack)

    async def _connect_persistent(self) -> None:
        if self._session is not None:
            return

        stack = AsyncExitStack()
        try:
            transport = await stack.enter_async_context(
                streamablehttp_client(self._url, timeout=self._timeout_seconds)
            )
            # streamablehttp_client yields (read_stream, write_stream, get_session_id).
            read_stream, write_stream, *_ = transport
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
        except asyncio.CancelledError as exc:
            # The MCP SDK's internal TaskGroup can raise CancelledError when
            # a background reader subtask dies during init (e.g. server is
            # down). That's a transport-layer failure from our point of view,
            # not an external cancel — convert so graceful degradation can
            # mark MCP unavailable without aborting FastAPI startup.
            await _best_effort_close(stack)
            raise McpTransientError(
                f"MCP session initialization was cancelled for {self._url}: {exc}"
            ) from exc
        except _TRANSIENT_EXC as exc:
            await _best_effort_close(stack)
            raise McpTransientError(
                f"failed to connect to MCP server at {self._url}: {exc}"
            ) from exc
        except Exception:
            await _best_effort_close(stack)
            raise

        self._exit_stack = stack
        self._session = session
        logger.info("remote_mcp.connected", extra={"url": self._url})

    async def aclose(self) -> None:
        """Close the MCP session and underlying transport."""
        if self._exit_stack is None:
            self._ready = False
            return
        stack = self._exit_stack
        self._exit_stack = None
        self._session = None
        self._ready = False
        try:
            await stack.aclose()
        except Exception:  # noqa: BLE001 — shutdown best-effort
            logger.exception("remote_mcp.close_error")

    async def discover_tools(self) -> list[McpTool]:
        if self._session is None:
            return await self._discover_tools_once()

        session = await self._require_session()
        try:
            result = await session.list_tools()
        except _TRANSIENT_EXC as exc:
            raise McpTransientError(
                f"list_tools transport failure: {exc}"
            ) from exc
        except McpError as exc:
            if _is_session_terminated(exc):
                await self._reset_session()
                session = await self._require_session()
                try:
                    result = await session.list_tools()
                except _TRANSIENT_EXC as retry_exc:
                    raise McpTransientError(
                        f"list_tools transport failure after reconnect: {retry_exc}"
                    ) from retry_exc
                except McpError as retry_exc:
                    raise McpToolError(f"list_tools failed: {retry_exc}") from retry_exc
                return [_tool_to_model(tool) for tool in result.tools]
            raise McpToolError(f"list_tools failed: {exc}") from exc

        return [_tool_to_model(tool) for tool in result.tools]

    async def call_tool(
        self, tool: str, inputs: dict[str, object]
    ) -> list[dict[str, object]]:
        if self._session is None:
            return await self._call_tool_once(tool, inputs)

        session = await self._require_session()

        arguments: dict[str, Any] = dict(inputs)
        read_timeout = timedelta(seconds=self._timeout_seconds)
        try:
            result = await session.call_tool(
                tool,
                arguments=arguments,
                read_timeout_seconds=read_timeout,
            )
        except _TRANSIENT_EXC as exc:
            raise McpTransientError(
                f"call_tool {tool!r} transport failure: {exc}", tool=tool
            ) from exc
        except McpError as exc:
            if not _is_session_terminated(exc):
                raise McpToolError(
                    f"call_tool {tool!r} failed: {exc}", tool=tool
                ) from exc
            await self._reset_session()
            session = await self._require_session()
            try:
                result = await session.call_tool(
                    tool,
                    arguments=arguments,
                    read_timeout_seconds=read_timeout,
                )
            except _TRANSIENT_EXC as retry_exc:
                raise McpTransientError(
                    f"call_tool {tool!r} transport failure after reconnect: {retry_exc}",
                    tool=tool,
                ) from retry_exc
            except McpError as retry_exc:
                raise McpToolError(
                    f"call_tool {tool!r} failed: {retry_exc}", tool=tool
                ) from retry_exc

        if result.isError:
            raise McpToolError(_extract_error_message(result), tool=tool)

        return _normalize_result(result, tool=tool)

    async def _discover_tools_once(self) -> list[McpTool]:
        try:
            async with self._open_session() as session:
                result = await session.list_tools()
        except _TRANSIENT_EXC as exc:
            raise McpTransientError(
                f"list_tools transport failure: {exc}"
            ) from exc
        except McpError as exc:
            if not _is_session_terminated(exc):
                raise McpToolError(f"list_tools failed: {exc}") from exc
            logger.info(
                "remote_mcp.session_terminated_retry",
                extra={"url": self._url},
            )
            try:
                async with self._open_session() as session:
                    result = await session.list_tools()
            except _TRANSIENT_EXC as retry_exc:
                raise McpTransientError(
                    f"list_tools transport failure after reconnect: {retry_exc}"
                ) from retry_exc
            except McpError as retry_exc:
                raise McpToolError(f"list_tools failed: {retry_exc}") from retry_exc

        return [_tool_to_model(tool) for tool in result.tools]

    async def _call_tool_once(
        self, tool: str, inputs: dict[str, object]
    ) -> list[dict[str, object]]:
        arguments: dict[str, Any] = dict(inputs)
        read_timeout = timedelta(seconds=self._timeout_seconds)
        try:
            async with self._open_session() as session:
                result = await session.call_tool(
                    tool,
                    arguments=arguments,
                    read_timeout_seconds=read_timeout,
                )
        except _TRANSIENT_EXC as exc:
            raise McpTransientError(
                f"call_tool {tool!r} transport failure: {exc}", tool=tool
            ) from exc
        except McpError as exc:
            if not _is_session_terminated(exc):
                raise McpToolError(
                    f"call_tool {tool!r} failed: {exc}", tool=tool
                ) from exc
            logger.info(
                "remote_mcp.session_terminated_retry",
                extra={"url": self._url},
            )
            try:
                async with self._open_session() as session:
                    result = await session.call_tool(
                        tool,
                        arguments=arguments,
                        read_timeout_seconds=read_timeout,
                    )
            except _TRANSIENT_EXC as retry_exc:
                raise McpTransientError(
                    f"call_tool {tool!r} transport failure after reconnect: {retry_exc}",
                    tool=tool,
                ) from retry_exc
            except McpError as retry_exc:
                raise McpToolError(
                    f"call_tool {tool!r} failed: {retry_exc}", tool=tool
                ) from retry_exc

        if result.isError:
            raise McpToolError(_extract_error_message(result), tool=tool)

        return _normalize_result(result, tool=tool)

    async def _require_session(self) -> ClientSession:
        if self._session is None:
            await self._connect_persistent()
        if self._session is None:  # pragma: no cover — connect() raises on failure
            raise McpTransientError("MCP session is not initialized")
        return self._session

    async def _reset_session(self) -> None:
        logger.info(
            "remote_mcp.session_terminated_reconnect",
            extra={"url": self._url},
        )
        await self.aclose()
        await self.connect()


def _tool_to_model(tool: Tool) -> McpTool:
    schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
    return McpTool(
        name=tool.name,
        description=tool.description or "",
        input_schema=dict(schema),
    )


def _is_session_terminated(exc: McpError) -> bool:
    return "session terminated" in str(exc).lower()


def _normalize_result(
    result: CallToolResult, *, tool: str
) -> list[dict[str, object]]:
    """Map an MCP CallToolResult to a list of result records.

    Preference order:
    1. `structuredContent` if present (dict wrapped to single-item list,
       list of dicts returned as-is, list with `results` key unwrapped).
    2. Text content parsed as JSON (object wrapped to single-item list,
       array of objects returned as-is).
    """
    structured = result.structuredContent
    if structured is not None:
        return _coerce_records(structured, tool=tool)

    payloads: list[dict[str, object]] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parsed = _parse_json_safely(block.text)
            if parsed is None:
                raise McpToolError(
                    f"tool {tool!r} returned non-JSON text content",
                    tool=tool,
                )
            payloads.extend(_coerce_records(parsed, tool=tool))
        else:
            raise McpToolError(
                f"tool {tool!r} returned unsupported content type "
                f"{type(block).__name__}",
                tool=tool,
            )
    return payloads


def _parse_json_safely(text: str) -> object | None:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _extract_error_message(result: CallToolResult) -> str:
    for block in result.content:
        if isinstance(block, TextContent) and block.text:
            return block.text
    return "tool returned isError=true with no message"
