# Polygon Zone Editing — Postmortem and Next Iteration Brief

- Date: 2026-03-19
- Context: Frontend polygon zone editing iteration
- Status: Rework required (current implementation should be reverted)

## 1) Product Contract (Locked from discussion)

We agreed this interaction model:

1. Selection states:
   - `0 selected zones`
   - `1 selected zone`
   - `multi selected zones`
1. Behavior by state:
   - If `0 selected` and no zones exist: single click creates first zone with
   first point.
   - If `0 selected` and zones exist: single click creates new zone with first point.
   - If `1 selected`: single click adds point to selected zone.
   - If `multi selected`: adding points is disabled; empty click clears selection.
   - `Esc` clears selection.
1. Point vs zone actions:
   - Double-click point => point action menu (delete point / delete zone fallback).
   - Double-click zone body => zone action menu.
   - If ambiguous, point wins.
1. Validation:
   - Self-intersecting polygons are blocked.
   - If point deletion causes `<3` points, treat as zone deletion and message
   should say delete zone.
1. Multi-select:
   - Keep for bulk actions (scan/remove), not multi-edit point creation.

## 2) What failed in the implementation

Even though tests eventually passed, real app behavior did not match
expectation except one part (point deletion). Main failures:

- Double-click behavior was not robustly real:
  - We relied partly on click-timing heuristics in places.
  - This creates inconsistent UX and event ambiguity in real interaction.
- Some tests validated proxy behavior, not true behavior:
  - At least one zone-action case used right-click fallback in test while
  requirement was double-click distinction.
  - This made test pass while user-facing behavior still felt wrong.
- Dragging vertices felt broken (“stops after a little drag”):
  - This is a critical UX regression and confirms architecture issue in edit
  loop.

## 3) Root-cause reflection (important)

### A. Drag interruption root cause (most critical)

The map interaction effect was coupled to frequently changing state and rebuilt
marker layers/handlers too often. During drag, state updates triggered
rerenders/effect cleanup/rebind cycles, so marker interaction got interrupted.
Symptom:

- Drag starts, moves slightly, then effectively loses continuous control.
Likely technical mechanism:
- Drag event updates polygon state continuously.
- Effect dependencies include polygon/zone state.
- Effect teardown clears/recreates markers and handlers.
- Ongoing drag session gets disrupted.

### B. Interaction model was implemented with too much implicit behavior

Point and zone actions were driven through low-level event juggling rather than
an explicit editor state machine. This makes edge cases fragile:

- point-vs-zone conflict
- double-click semantics
- add-point gating by selection state

### C. Test contract and UX contract drifted

E2E assertions were too close to implementation details in some cases and
allowed “green tests, wrong UX”.

## 4) Message to future iteration (do this differently)

### Non-negotiable architecture direction

Implement polygon editing with explicit editor state, not implicit event coupling:

- `activeEditZoneId: string | null`
- `selectedZoneIds: string[]`
- `draftZone` or `draftZoneId` explicit
- `interactionMode`: `idle | add_point | move_point | point_menu | zone_menu | bulk_select`

Do not infer mode from scattered conditions.

### Draging must be stabilized

- Do not recreate markers during active drag.
- Update geometry in-place during drag; commit state on `dragend` (or throttled
updates that do not recreate handlers).
- Keep marker instances stable with per-zone feature groups/layers.
- Separate render sync from interaction binding:
  - bind once
  - update data without full teardown

### Event priority contract

- Point target hit-test first.
- Zone body second.
- Empty map third.
- Keep this ordering explicit and testable.

### Selection + add-point contract

- Enforce exactly:
  - 0 selected => new zone creation on click.
  - 1 selected => add point.
  - >1 selected => no add point; empty click clears selection.
- `Esc` always clears selection.

### Validation contract

- Self-intersection validation before commit.
- Triangle point delete => zone delete with explicit message copy.

## 5) Test strategy correction

Future tests must prove real UX, not shortcuts:

1. Keep E2E contract tests, but ensure gestures match requirement exactly.
2. Add test ids for:
   - zone polygon
   - point marker
   - active/selected states
   - point menu
   - zone menu
   - delete actions
3. Add a dedicated drag behavior test:
   - drag a vertex long enough
   - verify cursor tracking continuity
   - verify final position meaningfully changed
4. Add manual exploratory checklist for pointer interactions on real browser session:
   - slow drag, fast drag, double-click edge, zoomed in/out.

## 6) Suggested implementation order for next attempt

1. Introduce explicit zone editor state model.
2. Refactor map interaction handlers to avoid teardown-on-drag.
3. Re-implement point/zone action routing with deterministic hit priority.
4. Re-implement add-point rules by selection state.
5. Re-add self-intersection + delete-zone-on-<3 behavior.
6. Update E2E tests to strict gesture validation.
7. Manual QA pass focused on dragging and double-click conflict zones.

## 7) Acceptance criteria before merge

- User can reliably drag any point without drag interruption.
- Point and zone double-click actions are distinct and consistent.
- Multi-zone creation/selection behavior matches contract.
- E2E contract suite passes with no expected-fail shortcuts.
- Manual UX verification confirms no “green tests, broken feel” gap.

---

## Short candid summary

This iteration optimized for test green-ness too early and underweighted
interaction stability. Next iteration must center around a stable editor state
model + stable drag lifecycle first, then tests as strict proof. If you want,
once write mode is enabled I can place this exactly into docs/iterations/...
and also add a short index line in docs/DECISIONS.md pointing to it.
