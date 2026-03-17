# AI Prompt Series Playbook — Non-Hallucinatory Development

This playbook gives a full sequence of prompts to drive AI work safely for this project.
Use these prompts in order. Do not skip quality gates.

---

## 0) How to Use This Playbook

- One chat session should handle one bounded objective.
- Require the AI to show assumptions, contracts, and verification before code merge.
- If context gets long/noisy, switch to Summarize Mode using the prompts in Section 10.
- If AI output conflicts with MCP contracts, contract wins.

---

## 1) Session Bootstrap Prompt (always first)

Copy-paste:

```text
You are helping on an offline SAR swarm system using MCP-first architecture.
Follow these hard rules:
1) No drone teleportation. Position changes only via world step/tick.
2) Agent decisions must be grounded in MCP tool outputs, not assumptions.
3) Survivor lifecycle is missing -> found only (no drone rescue mechanic).
4) Path-level planning only (assign_path), not move_to + guessed stepping.
5) step() must return events; do not rely on hidden state.
6) World clock and LLM thinking clock are separate.
7) Rolling 3-step planning window: each drone always has next 3 actions; replan one step before window end.

Before coding, restate constraints as a checklist, then propose a minimal plan.
If anything is uncertain, ask specific questions instead of guessing.
```

Expected AI output:

- Constraint checklist
- Minimal plan
- Explicit uncertainties

---

## 2) Contract Lock Prompt (before implementation)

Copy-paste:

```text
Define or update contracts first. Provide exact request/response schemas for:
- list_drones
- assign_path
- recall_drone
- get_world_snapshot
- step

Requirements:
- Distinguish estimate vs confirmed state.
- Include success/error structure.
- Include event schema for step().
- Include validation errors for malformed IDs, out-of-grid coordinates, and impossible waypoints.

Output format:
1) Proposed schema diff
2) Backward compatibility notes
3) Risks and mitigations
No code yet.
```

---

## 3) Architecture Decision Prompt (before coding)

Copy-paste:

```text
Create implementation decisions with strict module boundaries:
- world layer: deterministic simulation + physics
- mcp_server layer: protocol adapter only
- agent layer: orchestration/planning only

For each boundary, list:
- allowed dependencies
- forbidden dependencies
- anti-hallucination rationale

Then provide a small ADR-style decision summary.
```

---

## 4) Implementation Prompt (code generation)

Copy-paste:

```text
Implement only the approved contract diff and nothing extra.

Rules:
- Small, reviewable patches.
- No hidden shortcuts across layers.
- No hard-coded drone IDs.
- step() is the only time advancement mechanism.
- assign_path queues intent only; never teleports.
- Preserve existing style and public interfaces unless explicitly changed by the contract.

After edits, provide:
1) Changed files
2) Why each change is required
3) Which constraint each change satisfies
```

---

## 5) Test Generation Prompt (must run after code changes)

Copy-paste:

```text
Add or update tests for only the changed behavior.

Required test coverage:
1) Contract shape validation per MCP tool
2) Determinism replay for fixed seed + same command stream
3) No-teleport invariant per tick speed bound
4) Survivor state missing -> found only
5) Multi-detection scan returns all detections
6) Rolling 3-step planning window trigger behavior

Return:
- New/updated test files
- Exact scenarios and expected outcomes
- Any uncovered risk and why
```

---

## 6) Verification Prompt (anti-hallucination review)

Copy-paste:

```text
Perform a strict hallucination audit on your own changes.

Check for:
- implied success without evidence
- stale assumptions about drone positions
- dropped events or payload truncation
- dead config fields
- mismatch between prompt instructions and actual code behavior

Output a table:
Issue | Found? | Evidence | Fix applied
If no issue found, provide proof points from code/tests.
```

---

## 7) Failure Recovery Prompts (when AI goes wrong)

### A) If AI gives vague/hand-wavy answer

```text
Your answer is too abstract. Re-do with concrete artifacts only:
- exact file changes
- exact contract fields
- exact tests
- exact failure modes
Do not give generic advice.
```

### B) If AI introduces bad code or scope creep

```text
Rollback to minimal scope.
Keep only changes required by the approved contract diff.
List and remove non-essential additions.
Then re-run focused tests.
```

### C) If AI hallucinates behavior not in code

```text
Evidence required now:
For every claim, cite the exact file and function where it is implemented.
If implementation is missing, mark as NOT IMPLEMENTED and propose a minimal patch.
No assumptions allowed.
```

### D) If tests fail repeatedly

```text
Stop broad edits.
Identify one root cause at a time using failing test output.
Apply one minimal fix, rerun only related tests, then expand.
Provide root-cause note before next patch.
```

---

## 8) Edge Case Prompt Pack (targeted)

### Edge Case 1 — Invalid drone ID format

```text
Handle invalid drone IDs safely.
Expected behavior: structured error, no crash, no state mutation.
Add tests for malformed IDs and unknown IDs.
```

### Edge Case 2 — Waypoints out of grid / blocked

```text
Reject impossible waypoints with detailed error reason.
Do not partially teleport or silently clip points.
Add tests for out-of-bounds and obstacle collision input.
```

### Edge Case 3 — Low battery during active path

```text
If battery crosses threshold during execution, emit battery_low/battery_critical event and enforce recall policy.
Add tests for transition timing and event payload.
```

### Edge Case 4 — Multiple survivor detections same tick

```text
Ensure scan_detection event includes full detections array.
No truncation to first survivor.
Add regression test for 2+ detections in range.
```

### Edge Case 5 — LLM delay and action continuity

```text
Validate that drone queues do not run empty due to LLM latency.
Use rolling 3-step window; replan one step before window end.
Add test for cadence 2,5,8,...
```

---

## 9) PR Gate Prompt (before merge)

Copy-paste:

```text
Evaluate this branch against project gates.
Return PASS/FAIL for:
- contract integrity
- determinism
- physics/state correctness
- integration reliability
- regression protection

For any FAIL, provide exact blocker and smallest fix.
No merge recommendation unless all required gates pass.
```

---

## 10) When to Switch Chat vs Summarize/Compress

Use this decision rule:

Stay in normal chat when:

- Objective is single and clear.
- Fewer than ~8 files touched.
- Recent context still coherent.

Switch to Summarize Mode when any of these happen:

- Context becomes long/noisy and decisions are hard to track.
- More than ~8 files or multiple subsystems touched.
- Repeated misunderstandings across 2+ turns.
- You need a clean handoff checkpoint before next implementation phase.

### Summarize Mode Prompt (checkpoint)

```text
Switch to Summarize Mode.
Create a compact checkpoint with:
1) Goal and non-negotiable constraints
2) Decisions already locked
3) Open risks and blockers
4) Exact next 3 implementation steps
5) Files changed and why
6) Pending tests and expected results

Keep it concise and factual so a new chat can continue without loss.
```

### Resume-From-Summary Prompt (new chat/session)

```text
Use this summary as the only source of truth.
Do not re-open settled decisions unless they conflict with contracts.
Start with Step 1 from the listed next steps.
Before coding, restate constraints and acceptance criteria.
```

---

## 11) Anti-Regression System Prompt (optional, reusable)

Copy-paste at the top of any risky session:

```text
You must optimize for correctness over speed.
Never infer hidden state.
Never claim implementation without code evidence.
Never bypass MCP contracts.
Never move drones outside world-step progression.
If uncertain, ask clarifying questions or mark unknown explicitly.
```

---

## 12) Quick Operator Checklist (Human-in-the-loop)

Before accepting AI output, verify:

- Did AI show evidence for each major claim?
- Did AI preserve no-teleport and dual-clock invariants?
- Did AI avoid hard-coded drone IDs?
- Did AI add/update tests tied to changed behavior?
- Did AI avoid scope creep?

If any answer is “no”, run Section 7 recovery prompts before proceeding.
