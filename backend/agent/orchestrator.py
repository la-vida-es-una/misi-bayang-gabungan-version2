"""
Mission Orchestrator — primary entry point for all teams.

Wires together:
- LangGraph ReAct agent with tool-wrapped MCP protocol methods
- Mission logger + observer bridge
- Context builder

"""

from __future__ import annotations

import json
from typing import Any, final

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool as langchain_tool

from langgraph.prebuilt import create_react_agent

# The function "create_react_agent" is deprecated  create_react_agent has been
# moved to `langchain.agents`. Please update your import to `from
# langchain.agents import create_agent`. [reportDeprecated]
from langchain.agents import create_agent as create_react_agent

from config.settings import Settings, get_settings

from .interfaces import (
    AgentObserverProtocol,
    MCPClientProtocol,
    NullObserver,
)
from .mission_log import MissionLogger
from .prompts import SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════════════════
#  Mission Orchestrator
# ═══════════════════════════════════════════════════════════════════════


@final
class MissionOrchestrator:
    """
    Primary entry point for all teams.

    Constructor uses dependency injection — the MCP client, settings,
    and observer are all injected.  No external module is ever imported
    internally.

    Args:
        mcp_client: Any object satisfying :class:`MCPClientProtocol`.
        settings: Application settings (auto-loaded if ``None``).
        observer: Optional frontend / API bridge (``NullObserver`` if ``None``).
    """

    def __init__(
        self,
        mcp_client: MCPClientProtocol,
        settings: Settings | None = None,
        observer: AgentObserverProtocol | None = None,
    ) -> None:
        self._mcp = mcp_client
        self._settings = settings or get_settings()
        self._observer = observer or NullObserver()

        # ── internal components ─────────────────────────────────────
        self._logger = MissionLogger(log_dir=self._settings.LOG_DIR)
        self._llm = self._settings.get_llm()

        # ── build LangGraph agent ───────────────────────────────────
        self._tools = self._build_tools()
        self._agent = create_react_agent(
            model=self._llm,
            tools=self._tools,
            system_prompt=SYSTEM_PROMPT,
        )

        # ── mission tracking ────────────────────────────────────────
        self._step = 0
        self._survivors_found: list[dict[str, Any]] = []

    # ── tool construction ───────────────────────────────────────────

    def _build_tools(self) -> list[Any]:
        """
        Wrap each MCPClientProtocol method as a LangChain tool.

        Uses closure over ``self._mcp`` so the tools can call the
        injected MCP client without importing anything.
        """
        mcp = self._mcp
        logger = self._logger
        observer = self._observer
        orchestrator = self

        @langchain_tool
        async def list_active_drones() -> str:
            """List all active drones. Returns {"drones": ["drone_0", ...]}."""
            result = await mcp.list_active_drones()
            result_dict = dict(result)
            observer.on_tool_call("list_active_drones", {}, result_dict)
            return json.dumps(result_dict)

        @langchain_tool
        async def get_battery_status(drone_id: str) -> str:
            """Get drone battery, position, state. Input: drone_id.
            Returns {"drone_id", "battery", "x", "y", "state"}."""
            result = await mcp.get_battery_status(drone_id)
            result_dict = dict(result)
            observer.on_tool_call(
                "get_battery_status", {"drone_id": drone_id}, result_dict
            )
            return json.dumps(result_dict)

        @langchain_tool
        async def move_to(drone_id: str, x: int, y: int) -> str:
            """Set a waypoint for drone at (x,y). Drone navigates at configured
            speed — does NOT teleport. Call step(N) after this to advance the
            simulation. Returns {"success", "drone_id", "x", "y"}."""
            result = await mcp.move_to(drone_id, x, y)
            result_dict = dict(result)
            observer.on_tool_call(
                "move_to", {"drone_id": drone_id, "x": x, "y": y}, result_dict
            )
            return json.dumps(result_dict)

        @langchain_tool
        async def step(ticks: int = 1) -> str:
            """Advance the simulation by ticks steps so drones physically move
            toward their waypoints. Call this after move_to before thermal_scan.
            Returns {"success", "new_tick"}."""
            result = await mcp.step_world(ticks)
            result_dict = dict(result)
            observer.on_tool_call("step", {"ticks": ticks}, result_dict)
            orchestrator._step = result_dict.get("new_tick", orchestrator._step)
            return json.dumps(result_dict)

        @langchain_tool
        async def thermal_scan(drone_id: str) -> str:
            """Thermal scan at drone's current position. Input: drone_id.
            Returns {"survivor_detected", "confidence", "x", "y"}.
            If survivor_detected=true, call broadcast_alert."""
            result = await mcp.thermal_scan(drone_id)
            result_dict = dict(result)
            observer.on_tool_call("thermal_scan", {"drone_id": drone_id}, result_dict)

            if result["survivor_detected"]:
                orchestrator._survivors_found.append(result_dict)
                logger.log_survivor(
                    orchestrator._step,
                    int(result["x"]),
                    int(result["y"]),
                    drone_id,
                    float(result["confidence"]),
                )
                observer.on_survivor_found(
                    int(result["x"]),
                    int(result["y"]),
                    float(result["confidence"]),
                )
            return json.dumps(result_dict)

        @langchain_tool
        async def return_to_base(drone_id: str) -> str:
            """Send drone to recharge. Use when battery<25%. Input: drone_id."""
            result = await mcp.return_to_base(drone_id)
            result_dict = dict(result)
            observer.on_tool_call("return_to_base", {"drone_id": drone_id}, result_dict)
            logger.log_battery_event(orchestrator._step, drone_id, 0, "recall")
            return json.dumps(result_dict)

        @langchain_tool
        async def get_grid_map() -> str:
            """Get scanned cells and found survivors.
            Returns {"scanned": [[x,y],...], "survivors": [[x,y],...]}."""
            result = await mcp.get_grid_map()
            result_dict = dict(result)
            observer.on_tool_call("get_grid_map", {}, result_dict)
            return json.dumps(result_dict)

        @langchain_tool
        async def broadcast_alert(x: int, y: int, message: str) -> str:
            """Broadcast survivor alert. Input: x, y, message."""
            result = await mcp.broadcast_alert(x, y, message)
            result_dict = dict(result)
            observer.on_tool_call(
                "broadcast_alert", {"x": x, "y": y, "message": message}, result_dict
            )
            return json.dumps(result_dict)

        return [
            list_active_drones,
            get_battery_status,
            move_to,
            step,
            thermal_scan,
            return_to_base,
            get_grid_map,
            broadcast_alert,
        ]

    # ── context builder ─────────────────────────────────────────────

    def _build_context(self) -> str:
        """Minimal mission context injected into the human message."""
        survivors_summary = (
            f"{len(self._survivors_found)} survivors found"
            if self._survivors_found
            else "No survivors found yet"
        )
        return (
            f"\n\n══ MISSION CONTEXT ══\n"
            f"Step: {self._step}\n"
            f"Survivors: {survivors_summary}\n"
        )

    # ── main mission loop ───────────────────────────────────────────

    async def run_mission(
        self,
        objective: str = "Search the grid for survivors",
        max_steps: int | None = None,
    ) -> dict[str, Any]:
        """
        Execute the rescue mission.

        Invokes the ReAct agent once with the full step budget.
        The LLM drives the mission to completion via tool calls.

        Args:
            objective: High-level mission objective text.
            max_steps: Override ``MAX_MISSION_STEPS`` from settings.

        Returns:
            Mission summary dict from :meth:`MissionLogger.get_summary`.
        """
        effective_max_steps = max_steps or self._settings.MAX_MISSION_STEPS

        try:
            self._step = 0
            self._logger.log_reasoning(0, f"Mission objective: {objective}")
            self._observer.on_step_start(0, {"objective": objective})
            self._observer.on_reasoning(0, f"Mission objective: {objective}")

            from .callbacks import ObserverCallbackHandler

            handler = ObserverCallbackHandler(self._observer)

            human_content = objective + self._build_context()
            self._observer.on_step_start(1, {"human_message": human_content})

            _ = await self._agent.ainvoke(
                {"messages": [HumanMessage(content=human_content)]},
                config={
                    "recursion_limit": effective_max_steps * 2,
                    "callbacks": [handler],
                },
            )

            self._step = handler.step

        except Exception as exc:
            self._logger.log_reasoning(
                self._step,
                f"Mission terminated with error: {type(exc).__name__}: {exc}",
            )
            raise

        finally:
            summary = self._logger.get_summary()
            self._observer.on_mission_complete(summary)
            self._logger.save()

        return summary


# ═══════════════════════════════════════════════════════════════════════
#  Convenience Factory
# ═══════════════════════════════════════════════════════════════════════


def create_agent(
    mcp_client: MCPClientProtocol,
    settings: Settings | None = None,
    observer: AgentObserverProtocol | None = None,
) -> MissionOrchestrator:
    """
    Convenience factory for creating a :class:`MissionOrchestrator`.

    Usage::

        from agent import create_agent, RealMCPClient
        from mcp_server.context import mcp

        agent = create_agent(mcp_client=RealMCPClient(mcp))
        result = await agent.run_mission()

    Args:
        mcp_client: An MCP client satisfying :class:`MCPClientProtocol`.
        settings: Application settings (auto-loaded if ``None``).
        observer: Optional frontend / API bridge (``NullObserver`` if ``None``).
    """
    return MissionOrchestrator(
        mcp_client=mcp_client, settings=settings, observer=observer
    )
