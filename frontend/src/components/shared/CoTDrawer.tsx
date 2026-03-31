/**
 * ChatPanel -- AI chat interface with chain-of-thought visibility.
 *
 * Shows: system messages, user messages, agent thinking (CoT),
 * tool calls, tool results. Supports user input and stop/resume.
 */

import { useState, useRef, useEffect } from "react";
import { useMissionContext } from "../../context/MissionContext";
import { useMission } from "../../hooks/useMission";
import type { ChatMessage } from "../../types/mission";

const roleStyles: Record<string, { color: string; label: string; bg: string }> = {
  system: { color: "var(--text-secondary)", label: "SYS", bg: "rgba(255,255,255,0.03)" },
  user: { color: "var(--accent-color)", label: "YOU", bg: "rgba(68,170,255,0.05)" },
  assistant_thinking: { color: "#9e8cfc", label: "COT", bg: "rgba(158,140,252,0.05)" },
  tool_call: { color: "#44ffdd", label: "TOOL", bg: "rgba(68,255,221,0.05)" },
  tool_result: { color: "#88ff44", label: "RSLT", bg: "rgba(136,255,68,0.05)" },
  assistant: { color: "var(--success-color)", label: "AI", bg: "rgba(68,255,136,0.05)" },
  error: { color: "var(--danger-color)", label: "ERR", bg: "rgba(255,68,68,0.08)" },
};

const defaultStyle = { color: "var(--text-secondary)", label: "SYS", bg: "rgba(255,255,255,0.03)" };

/** Group consecutive tool_call + tool_result pairs by callId for display. */
function groupMessages(messages: ChatMessage[]): Array<{ call: ChatMessage; result?: ChatMessage } | ChatMessage> {
  const grouped: Array<{ call: ChatMessage; result?: ChatMessage } | ChatMessage> = [];
  let i = 0;
  while (i < messages.length) {
    const msg = messages[i]!;
    // If this is a tool_call with a callId, check if next message is its matching result
    if (msg.role === "tool_call" && msg.callId && i + 1 < messages.length) {
      const next = messages[i + 1]!;
      if (next.role === "tool_result" && next.callId === msg.callId) {
        grouped.push({ call: msg, result: next });
        i += 2;
        continue;
      }
    }
    grouped.push(msg);
    i++;
  }
  return grouped;
}

function isGrouped(item: { call: ChatMessage; result?: ChatMessage } | ChatMessage): item is { call: ChatMessage; result?: ChatMessage } {
  return "call" in item;
}

function ToolCallGroup({ call, result }: { call: ChatMessage; result?: ChatMessage }) {
  const callStyle = roleStyles["tool_call"] ?? defaultStyle;
  const resultStyle = roleStyles["tool_result"] ?? defaultStyle;
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={{
      background: callStyle.bg,
      borderLeft: `2px solid ${callStyle.color}`,
      padding: "6px 8px",
      marginBottom: 4,
      borderRadius: "0 4px 4px 0",
      fontSize: "0.72rem",
      lineHeight: 1.4,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
        <span style={{ color: callStyle.color, fontWeight: 700, fontSize: "0.62rem", letterSpacing: "0.06em" }}>
          {callStyle.label}
          {call.toolName && <span style={{ fontWeight: 400 }}> {call.toolName}</span>}
          {result && (
            <span style={{ color: resultStyle.color, marginLeft: 6, fontWeight: 400, fontSize: "0.58rem" }}>
              OK
            </span>
          )}
          {!result && (
            <span style={{ color: "var(--warning-color)", marginLeft: 6, fontWeight: 400, fontSize: "0.58rem" }}>
              pending...
            </span>
          )}
        </span>
        <button
          onClick={() => setExpanded(!expanded)}
          style={{ background: "none", border: "none", color: callStyle.color, cursor: "pointer", fontSize: "0.62rem", padding: 0 }}
        >
          {expanded ? "collapse" : "expand"}
        </button>
      </div>
      {expanded && (
        <div style={{ fontFamily: "monospace", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          <div style={{ color: "var(--text-primary)" }}>{call.content}</div>
          {result && (
            <div style={{ color: resultStyle.color, marginTop: 4, borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: 4 }}>
              {result.content}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const style = roleStyles[msg.role] ?? defaultStyle;
  const [expanded, setExpanded] = useState(msg.role === "user" || msg.role === "system");

  const isCollapsible = msg.role === "assistant_thinking" || msg.role === "tool_call" || msg.role === "tool_result";
  const truncated = msg.content.length > 120 && !expanded;

  return (
    <div style={{
      background: style.bg,
      borderLeft: `2px solid ${style.color}`,
      padding: "6px 8px",
      marginBottom: 4,
      borderRadius: "0 4px 4px 0",
      fontSize: "0.72rem",
      lineHeight: 1.4,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
        <span style={{ color: style.color, fontWeight: 700, fontSize: "0.62rem", letterSpacing: "0.06em" }}>
          {style.label}
          {msg.toolName && <span style={{ fontWeight: 400 }}> {msg.toolName}</span>}
        </span>
        {isCollapsible && (
          <button
            onClick={() => setExpanded(!expanded)}
            style={{ background: "none", border: "none", color: style.color, cursor: "pointer", fontSize: "0.62rem", padding: 0 }}
          >
            {expanded ? "collapse" : "expand"}
          </button>
        )}
      </div>
      <div style={{
        color: "var(--text-primary)",
        fontFamily: msg.role === "tool_call" || msg.role === "tool_result" ? "monospace" : "inherit",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        opacity: msg.role === "assistant_thinking" ? 0.7 : 1,
        maxHeight: (!expanded && isCollapsible) ? 0 : undefined,
        overflow: "hidden",
      }}>
        {truncated ? msg.content.slice(0, 120) + "..." : msg.content}
      </div>
    </div>
  );
}

export function ChatPanel() {
  const { state } = useMissionContext();
  const { promptAgent, stopAgent, restartAgent } = useMission();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const { chatMessages, agentRunning, phase } = state;
  const isRunning = phase === "running";

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatMessages.length, autoScroll]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || !isRunning) return;
    promptAgent(trimmed);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 6, padding: "0 2px",
      }}>
        <span style={{
          fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.08em",
          color: "var(--text-secondary)", textTransform: "uppercase",
        }}>
          AI Chat
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{
            fontSize: "0.6rem",
            color: agentRunning ? "var(--success-color)" : "var(--warning-color)",
          }}>
            {agentRunning ? "ACTIVE" : "STOPPED"}
          </span>
        </div>
      </div>

      {/* Message list */}
      <div
        style={{
          flex: 1, minHeight: 0, overflowY: "auto",
          background: "rgba(0,0,0,.2)", borderRadius: 4, padding: 6,
        }}
        onScroll={(e) => {
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          setAutoScroll(atBottom);
        }}
      >
        {chatMessages.length === 0 && (
          <div style={{ color: "var(--text-secondary)", fontSize: "0.72rem", padding: 8, textAlign: "center" }}>
            {isRunning
              ? "AI agent is running. Messages will appear here."
              : "Start a mission to activate the AI agent."}
          </div>
        )}
        {groupMessages(chatMessages).map((item, i) =>
          isGrouped(item) ? (
            <ToolCallGroup key={item.call.id} call={item.call} result={item.result} />
          ) : (
            <MessageBubble key={item.id} msg={item} />
          )
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      {isRunning && (
        <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
          <textarea
            rows={1}
            placeholder="Message the AI agent..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{
              flex: 1,
              background: "#0d1a2a",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              color: "var(--text-primary)",
              padding: "6px 8px",
              fontSize: "0.78rem",
              resize: "none",
              fontFamily: "inherit",
            }}
          />
          {agentRunning ? (
            <button
              onClick={stopAgent}
              title="Pause AI agent (drones keep current path)"
              style={{
                background: "rgba(255,68,68,0.1)",
                border: "1px solid var(--danger-color)",
                borderRadius: 4,
                color: "var(--danger-color)",
                cursor: "pointer",
                padding: "4px 8px",
                fontSize: "0.72rem",
                fontWeight: 700,
              }}
            >
              PAUSE
            </button>
          ) : (
            <button
              onClick={restartAgent}
              title="Restart AI agent with fresh conversation"
              style={{
                background: "rgba(68,255,136,0.1)",
                border: "1px solid var(--success-color)",
                borderRadius: 4,
                color: "var(--success-color)",
                cursor: "pointer",
                padding: "4px 8px",
                fontSize: "0.72rem",
                fontWeight: 700,
              }}
            >
              RESTART
            </button>
          )}
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            style={{
              background: input.trim() ? "rgba(68,170,255,0.1)" : "transparent",
              border: "1px solid var(--accent-color)",
              borderRadius: 4,
              color: "var(--accent-color)",
              cursor: input.trim() ? "pointer" : "not-allowed",
              padding: "4px 8px",
              fontSize: "0.72rem",
              fontWeight: 700,
              opacity: input.trim() ? 1 : 0.4,
            }}
          >
            SEND
          </button>
        </div>
      )}
    </div>
  );
}
