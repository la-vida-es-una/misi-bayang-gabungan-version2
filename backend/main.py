"""
Entry point.

Starts:
  1. FastMCP server  — MCP tools on  http://0.0.0.0:8000/mcp
  2. FastAPI server  — Mission REST  http://0.0.0.0:8000
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from mcp_server.server import mcp
from mission.receiver import router as mission_router

_ = load_dotenv()

# ── Structured logging ────────────────────────────────────────────────────────
# LOG_LEVEL env var controls verbosity: DEBUG, INFO (default), WARNING, ERROR
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet down noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


mcp_app = mcp.http_app()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging.getLogger("sar").info(
        "SAR Swarm Backend starting (LOG_LEVEL=%s)", _LOG_LEVEL
    )
    async with mcp_app.lifespan(mcp_app):
        yield


app = FastAPI(title="SAR Swarm Backend", lifespan=lifespan)

app.mount("/mcp", mcp_app)
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
        log_level=_LOG_LEVEL.lower(),
    )
