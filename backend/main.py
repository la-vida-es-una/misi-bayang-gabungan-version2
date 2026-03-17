"""
Entry point.

Starts:
  1. FastMCP server  — MCP tools on  http://0.0.0.0:8000/mcp
  2. FastAPI server  — Mission REST  http://0.0.0.0:8000
"""

from __future__ import annotations

import contextlib

# from typing import AsyncIterator
# Basedpyright Diagnostics:
# 1. This type is deprecated as of Python 3.9; use "collections.abc.AsyncIterator" instead [reportDeprecated]
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI

from mission.receiver import router as mission_router
from mcp_server.server import mcp


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield


app = FastAPI(title="SAR Swarm Backend", lifespan=lifespan)

app.mount("/mcp", mcp.http_app())
app.include_router(mission_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "sar-swarm-backend"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
