"""
Chain-of-Thought logger.

Every LLM reasoning step and every tool call must be logged here
BEFORE execution. This is the mission log required by the deliverables.

Two output channels:
  1. Console (stdout) — human-readable, colorful, via Python logging
  2. JSONL file — machine-readable, clean JSON, one object per line
     written exclusively by _emit(). The logging FileHandler is NOT used
     to avoid interleaving human-readable text into the JSONL file.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(exist_ok=True)

_session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
_log_path = _LOG_DIR / f"mission_{_session_id}.jsonl"

# Human-readable console output ONLY (no file handler — prevents JSONL corruption)
_console = logging.getLogger("cot")
_console.setLevel(logging.INFO)
if not _console.handlers:
    _console.addHandler(logging.StreamHandler(sys.stdout))
_console.propagate = False  # don't double-print via root logger

# Machine-readable JSONL file — written directly, not via logging
_jsonl_file = open(_log_path, "a", encoding="utf-8")  # noqa: SIM115


def _emit(record: dict[str, Any]) -> None:
    """Write a single JSON object to the JSONL file."""
    record["ts"] = datetime.now(timezone.utc).isoformat()
    line = json.dumps(record, ensure_ascii=False)
    _ = _jsonl_file.write(line + "\n")
    _jsonl_file.flush()


def log_reasoning(tick: int, thought: str) -> None:
    """Log LLM chain-of-thought reasoning text before any tool call."""
    _console.info("[tick=%d] CoT: %s", tick, thought)
    _emit({"kind": "cot", "tick": tick, "thought": thought})


def log_tool_call(
    tick: int, tool: str, args: dict[str, Any], call_id: str = ""
) -> None:
    """Log a tool call BEFORE it is dispatched."""
    _console.info("[tick=%d] CALL %s(%s)", tick, tool, args)
    record: dict[str, Any] = {"kind": "tool_call", "tick": tick, "tool": tool, "args": args}
    if call_id:
        record["call_id"] = call_id
    _emit(record)


def log_tool_result(
    tick: int, tool: str, result: dict[str, Any], call_id: str = ""
) -> None:
    """Log the result returned by a tool."""
    _console.info("[tick=%d] RESULT %s -> %s", tick, tool, result)
    record: dict[str, Any] = {"kind": "tool_result", "tick": tick, "tool": tool, "result": result}
    if call_id:
        record["call_id"] = call_id
    _emit(record)


def log_event(tick: int, event: dict[str, Any]) -> None:
    """Log a world event observed by the agent."""
    _console.info("[tick=%d] EVENT %s", tick, event)
    _emit({"kind": "world_event", "tick": tick, "event": event})


def log_mission(message: str) -> None:
    """Log a high-level mission status message."""
    _console.info("MISSION: %s", message)
    _emit({"kind": "mission", "message": message})
