"""
MISI BAYANG — Agent Package
============================

Autonomous swarm rescue intelligence agent built on LangChain ReAct.

Quick-start
-----------
::

    # ── With real MCP client ────────────────────────────────────────
    from agent import create_agent, RealMCPClient
    from mcp_server.context import mcp

    agent = create_agent(mcp_client=RealMCPClient(mcp))
    result = await agent.run_mission()

    # ── API team — bridging to frontend ────────────────────────────
    from agent import create_agent, AgentObserverProtocol

    class MyAPIObserver:
        def on_survivor_found(self, x, y, confidence):
            websocket.send({"type": "survivor", "x": x, "y": y})
        def on_step_start(self, step, context): ...
        def on_reasoning(self, step, text): ...
        def on_tool_call(self, tool_name, params, result): ...
        def on_mission_complete(self, summary): ...

    agent = create_agent(mcp_client=RealMCPClient(mcp), observer=MyAPIObserver())
    result = await agent.run_mission()
"""

from .callbacks import ObserverCallbackHandler
from .interfaces import (
    AgentObserverProtocol,
    MCPClientProtocol,
    NullObserver,
)
from .live_client import LiveMCPClient
from .mission_log import MissionLogger
from .orchestrator import MissionOrchestrator, create_agent
from .real_mcp_client import RealMCPClient

__all__ = [
    "MissionOrchestrator",
    "create_agent",
    "MissionLogger",
    "MCPClientProtocol",
    "AgentObserverProtocol",
    "NullObserver",
    "LiveMCPClient",
    "RealMCPClient",
    "ObserverCallbackHandler",
]
