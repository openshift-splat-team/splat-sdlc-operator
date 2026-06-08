"""Async client for the openshift-dep-tree MCP server (SSE or stdio transport)."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from agents.common.settings import OpenShiftAgentSettings

log = logging.getLogger(__name__)


def _normalize_repo(name: str) -> str:
    """Strip org prefix so MCP tools receive short names."""
    for prefix in ("openshift/", "operator-framework/"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _parse_result(result: Any) -> dict:
    """Extract parsed JSON from a CallToolResult."""
    if result.isError:
        texts = [block.text for block in result.content if hasattr(block, "text")]
        raise RuntimeError(f"MCP tool error: {' '.join(texts)}")
    for block in result.content:
        if hasattr(block, "text"):
            return json.loads(block.text)
    raise RuntimeError("MCP tool returned no text content")


class DepTreeClient:
    """Typed wrapper around the openshift-dep-tree MCP session."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def feature_impact(
        self,
        feature: str,
        *,
        platform: str = "",
        classification: str = "",
        top: int = 30,
        min_score: float = 10.0,
    ) -> dict:
        result = await self._session.call_tool(
            "feature_impact_tool",
            {
                "feature": feature,
                "platform": platform,
                "classification": classification,
                "top": top,
                "min_score": min_score,
            },
        )
        return _parse_result(result)

    async def get_repo_info(self, repo: str) -> dict:
        result = await self._session.call_tool(
            "get_repo_info",
            {"repo": _normalize_repo(repo)},
        )
        return _parse_result(result)

    async def get_repo_dependencies(self, repo: str) -> dict:
        result = await self._session.call_tool(
            "get_repo_dependencies",
            {"repo": _normalize_repo(repo)},
        )
        return _parse_result(result)

    async def get_repo_api_usage(self, repo: str) -> dict:
        result = await self._session.call_tool(
            "get_repo_api_usage",
            {"repo": _normalize_repo(repo)},
        )
        return _parse_result(result)

    async def search_repos(self, query: str) -> dict:
        result = await self._session.call_tool(
            "search_repos",
            {"query": query},
        )
        return _parse_result(result)


@asynccontextmanager
async def connect(settings: OpenShiftAgentSettings):
    """Open an MCP connection to the openshift-dep-tree server.

    Prefers SSE (mcp_server_url) when set; falls back to stdio.
    Yields a DepTreeClient.
    """
    if settings.mcp_server_url:
        log.info("Connecting to MCP dep-tree via SSE at %s", settings.mcp_server_url)
        async with sse_client(settings.mcp_server_url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                log.info("MCP dep-tree session initialized (SSE)")
                yield DepTreeClient(session)
    elif settings.mcp_server_script:
        log.info("Connecting to MCP dep-tree via stdio")
        env: dict[str, str] | None = None
        if settings.mcp_data_dir:
            env = {"MCP_DATA_DIR": settings.mcp_data_dir}

        server_params = StdioServerParameters(
            command=settings.mcp_server_command,
            args=[settings.mcp_server_script],
            env=env,
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                log.info("MCP dep-tree session initialized (stdio)")
                yield DepTreeClient(session)
    else:
        raise RuntimeError(
            "No MCP server configured; set MCP_SERVER_URL (preferred) "
            "or MCP_SERVER_SCRIPT in .env"
        )
