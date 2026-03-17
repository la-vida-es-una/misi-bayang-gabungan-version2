"""
Chain-of-Thought logger.

Every LLM reasoning step and every tool call must be logged here
BEFORE execution. This is the mission log required by the deliverables.
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

# Human-readable console output
_console = logging.getLogger("cot")
_console.setLevel(logging.INFO)
_console.addHandler(logging.StreamHandler(sys.stdout))

# Machine-readable JSONL for post-mission analysis
_file_handler = logging.FileHandler(_log_path, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_console.addHandler(_file_handler)


def _emit(record: dict[str, Any]) -> None:
    record["ts"] = datetime.now(timezone.utc).isoformat()
    line = json.dumps(record, ensure_ascii=False)
    _file_handler.stream.write(line + "\n")
    _file_handler.stream.flush()


def log_reasoning(tick: int, thought: str) -> None:
    """Log LLM chain-of-thought reasoning text before any tool call."""
    _console.info(f"[tick={tick}] 🧠 CoT: {thought}")
    _emit({"kind": "cot", "tick": tick, "thought": thought})


def log_tool_call(tick: int, tool: str, args: dict[str, Any]) -> None:
    """Log a tool call BEFORE it is dispatched."""
    _console.info(f"[tick={tick}] 🔧 CALL {tool}({args})")
    _emit({"kind": "tool_call", "tick": tick, "tool": tool, "args": args})


def log_tool_result(tick: int, tool: str, result: dict[str, Any]) -> None:
    """Log the result returned by a tool."""
    _console.info(f"[tick={tick}] ✅ RESULT {tool} → {result}")
    _emit({"kind": "tool_result", "tick": tick, "tool": tool, "result": result})


def log_event(tick: int, event: dict[str, Any]) -> None:
    """Log a world event observed by the agent."""
    _console.info(f"[tick={tick}] 🌍 EVENT {event}")
    _emit({"kind": "world_event", "tick": tick, "event": event})


def log_mission(message: str) -> None:
    """Log a high-level mission status message."""
    _console.info(f"📡 MISSION: {message}")
    _emit({"kind": "mission", "message": message})
