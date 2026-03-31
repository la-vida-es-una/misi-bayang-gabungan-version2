# Misi Bayang: Front-End Demo Script

## Detailed Walkthrough for Live Demonstration

> "What you're seeing here is the nerve center of our rescue operation. This is **MultiUAV Console** 

**Show on screen:** Point to the sidebar header showing "MultiUAV Console · SAR SWARM v2.0" with the orange "SIM" badge.

> "We're running in simulation mode right now,

**Action:** If not already in sim mode, click the "Enter Simulation Mode" button in the sidebar footer.

> "The system moves into setup phase. We're about to define the disaster zone and position our rescue base. In a real scenario, this would be the coordinates of the disaster area and where rescue operations are staging from."

- Sidebar shows `SimModeEntry` panel
- Map displays a Leaflet map centered on a coastal region
- Controls become available for placing the simulation base and boundary
**Action:** Click on the map once to place a base marker.


> "I'm placing the command base here—notice the orange marker with 'B'. This is where our drones originate and return for charging. In React, this is a stateful update that immediately triggers a re-render. The `useMissionContext` hook updates the `simConfig.base`, and the `BaseMarker` component responds instantly."
> "One of the challenges of building a real-time command center is managing state without lag. We're using React Context to centralize mission state—base position, zones, drone telemetry—and keeping components fast by minimizing re-renders. Only the components that depend on changed state re-render. The map itself is always live, but the re-renders happen in microseconds."

**Action:** Click and drag on the map to draw a rectangle around the search area.
> "Now I'm defining the boundary of the disaster zone—a rectangular perimeter that bounds where drones can operate. This is a drag-to-place interaction. As I drag, you can see a preview rectangle in real-time. This is Leaflet's geometric drawing capability, rendered natively on the canvas."
> "Leaflet is battle-tested for geographic visualization, and it renders all these vector elements—rectangles, circles, markers—directly on the map canvas. It doesn't depend on cloud tiles or APIs. Even if the internet goes down mid-operation, the map keeps rendering. We pre-load the terrain once, and everything else is client-side computation."

**Map status:** You should see a rectangle preview appear as you drag.

---

### Step 4: Confirm Boundary & Proceed [0:55]

**Action:** Click the "Confirm Boundary" or equivalent button (or confirm it appears automatically).

> "The boundary is locked in. Now the system moves to the **pending_zone** phase, where we can define search zones within this boundary. The UI automatically transitions — React's conditional rendering handles this. Different panels appear based on what phase we're in: setup, pending_zone, running, or ended."

**Status on screen:** Sidebar should now show `DrawZonePanel` asking to define zones.

---

## PART II: ZONE DEFINITION [1:00 - 1:45]

### Step 1: Draw Search Zones [1:00]

**Action:** Click multiple times on the map to define a polygon for the first search zone.

> "Each zone represents a search area where drones will systematically scan for survivors using thermal imaging. I'm clicking to place vertices of a polygon. With each click, a new vertex appears, and React updates the state (`drawingZonePoly`) to reflect the accumulated points."

**What you're seeing:**

- Vertex markers appear on the map (small circles at each click)
- A preview polygon connects the vertices
- The sidebar updates to show the number of vertices drawn

**Technical point:**

> "This is where React's reactivity shines. The `DrawZonePanel` component is watching the state. The moment I place a vertex, the state updates, React detects the change, and three things happen simultaneously without visible lag:
>
> 1. The vertex marker renders on the map
> 2. The polygon preview updates
> 3. The sidebar panel refreshes with new information
>
> No polling. No manual DOM manipulation. Just state → UI."

### Step 2: Complete the Zone & Add to List [1:20]

**Action:** Double-click or click a "Commit Zone" button to finalize the polygon.

> "I'm committing this zone. It's now officially part of the search plan. Notice that the zone appears in the zone list on the left sidebar with a distinctive color and status. This zone is **pending** — it hasn't started scanning yet."

**Sidebar update:** A zone card should appear in the zone list with:

- Zone ID
- Status indicator (pending, ready, scanning, etc.)
- Coverage percentage

---

### Step 3: Add More Zones (Optional) [1:35]

**Action:** Draw 2-3 more zones using the same process.

> "I'm adding a few more zones to cover different sectors of the disaster area. Each zone is independent, but they're coordinated. When the mission runs, the agent will decide which drones scan which zones based on their current battery levels and positions. It's not a fixed plan — it's adaptive."

**Show on screen:**

- Multiple zone polygons now visible on the map, each in a different color
- Zone list in sidebar growing
- Map becoming clearer as the disaster zone takes shape

---

## PART III: MISSION BRIEFING [1:45 - 2:15]

### Before We Start: Show the Drone Fleet

> "Now comes the critical part. Let me show you what the agent is about to work with."

**Action:** Stay in drawing mode or switch to a view that shows the current state.

> "At any moment, the agent can call the MCP discovery tool and ask, 'What drones are available right now?' The server responds with the active fleet. We have 5 drones ready. Here's what they can do:"

**Explain the Three Standardized Tools:**

1. **`move_to(drone_id, x, y)`**

   > "Move Drone A to position X, Y. Simple, right? But the agent doesn't just blindly call this. It calculates: How far is that position? How much battery will it cost? Is this drone the right choice for this task?"

2. **`get_battery_status(drone_id)`**

   > "Check how much power Drone A has left. This is called constantly during the mission. Battery is the constraint in the entire system. Every decision the agent makes is filtered through, 'Can my drones actually do this without running out of power?'"

3. **`thermal_scan(drone_id)`**
   > "Activate thermal imaging on Drone B. This is how we detect survivors—they emit heat signatures. But thermal scanning is expensive battery-wise. The agent balances coverage with power."

**MCP Protocol Callout:**

> "Every single one of these tool calls goes through the Model Context Protocol. There's no shortcut. No hard-coded drone movement. No assumptions about which drones exist. The agent must ask for capabilities, receive a response, and then decide. This standardization is what makes the system resilient and auditable."

---

### Show First Chain-of-Thought Example [2:00]

> "When the mission starts, the agent will reason like this—and you'll see it happen in real-time in the chat panel at the bottom left:"

**Simulate the reasoning:**

> **"I need to cover 5 zones with 5 drones. Let me check their current status:**
>
> - **Drone-Alpha:** 85% battery, position (3.314, 117.591) — this is our base
> - **Drone-Bravo:** 80% battery, position (3.312, 117.595) — 300 meters east
> - **Drone-Charlie:** 75% battery, position (3.316, 117.593) — 200 meters south
> - **Drone-Delta:** 70% battery, position (3.310, 117.588) — 500 meters west
> - **Drone-Echo:** 65% battery, position (3.318, 117.597) — 400 meters northeast
>
> **Decision: I'll hold Alpha in reserve at base (highest battery, most flexible). Bravo will take Zone-1 (closest, medium distance). Charlie will take Zone-2. Delta and Echo will handle Zones 3 and 4. Zone-5 needs a second pass after the first three zones are 80% scanned. I'm executing now.**"

> "This is not a script. This is real reasoning, every single time, adapting to the actual state of the system."

---

## PART IV: MISSION EXECUTION [2:15 - 8:00]

### Action: Start the Mission

**Action:** Click "Launch Mission" or equivalent button.

> "And we're live. The agent has taken the controls. From this moment forward, everything you see is the result of:
>
> 1. Agent reasoning (visible in the chat panel)
> 2. Tool calls through MCP (move_to, get_battery_status, thermal_scan)
> 3. Real-time visualization updates
>
> No human intervention. Pure orchestration."

---

### What to Watch — 4 Key Areas

#### 1. The Map (Right Side) — The Situational Awareness Layer

> "Look at the map. Several things are happening in real-time:"

**Drone Movement:**

- Blue dots representing drones move across the map
- Each drone has a trajectory trace (a thin line showing where it's been)
- As drones reach waypoints, the trace updates

> "These aren't pre-recorded. These are live position updates. Every move_to() call result flows through the SSE (Server-Sent Events) connection, and React receives the update, updates the mission state, and the `DroneMarkerLayer` re-renders the positions. This happens 30+ times per second."

**Thermal Scan Coverage:**

- As drones execute thermal_scan(), the map shows expanding circles/polygons representing scanned areas
- The `CoverageCanvas` paints these areas in real-time

> "That expanding coverage on the map represents our search progress. Where we've already scanned, we've confirmed no survivors are hidden."

**Survivor Detection:**

- Red markers appear on the map as survivors are detected
- These are `SurvivorMarkerLayer` components responding to state updates

> "Red markers are survivors detected by thermal imaging. Notice how they only appear after a drone has scanned an area. This is reactive — the agent plans movement, drones move, thermal scan executes, survivors are detected. The UI is always reflecting the true state of the disaster zone."

**Zone Polygons:**

- Each zone polygon changes color as its status progresses (pending → active → scanning → complete)
- Completed zones fade or change to indicate they're done

> "These colored zones on the map are the search areas. As the agent assigns drones to zones, they light up. As coverage increases, they fill with color. This gives rescue coordinators instant understanding of mission progress without reading numbers."

**Technical point:**

> "All of this is rendered by Leaflet.js. Why Leaflet? Because it's lightweight, it renders client-side, and it doesn't depend on cloud mapping APIs. If the internet drops during the mission, the map keeps showing the current state because all the rendering happens right here, in the browser."

---

#### 2. The Drone Status Panel (Top Left) — Real-Time Telemetry

> "Now look at the sidebar. You're seeing live battery levels and drone status."

**Show the Drone Cards:**

- Each drone has a card showing:
  - Drone ID
  - Current battery percentage (with color coding — green for high, yellow for medium, orange for low)
  - Current position (lat/lon)
  - Status (moving, scanning, idle, returning_to_base, charging)
  - Mission assignments

> "Battery is everything. Notice the `DroneCard` component displays the battery as a percentage with a progress bar. As the agent's tool calls drain battery, this value updates in real-time. The color shifts from green (70%+) to yellow (30-70%) to orange (below 30%) automatically."

**Strategic Resource Management in Action:**

> "Watch what happens when a drone's battery drops below 30%. The agent doesn't keep it in the field. It sends a 'return_to_base' command. That drone heads home, the other drones adjust their assignments, and coverage continues. This is why Chain-of-Thought reasoning is critical — the agent is constantly asking, 'Do I have enough power to do what I want?'"

**Technical point:**

> "These drone cards are React components that subscribe to mission state changes via context. The moment a drone's battery property updates, TypeScript ensures we're accessing the right property with the right type. No runtime errors. No surprises. This is why we chose TypeScript — in a life-or-death scenario, a type error is unacceptable."

---

#### 3. The Chain-of-Thought Log (Bottom Left) — Agent Reasoning

> "This is the most important view. This is the agent's thinking, made transparent."

**What the Chat Panel Shows:**

**System Messages (gray):**

- Initialization messages
- Mission start notification
- Phase transitions

**Assistant Thinking (purple, labeled "COT"):**

- The agent's reasoning before each action
- Example: `"Drone-Bravo has 72% battery. Zone-2 is 600 meters away, estimated cost 8% battery. After scanning, it will have 64% battery, enough to return home. Decision: send Bravo to Zone-2."`

**Tool Calls (cyan, labeled "TOOL"):**

- Structured tool invocations with parameters
- Example: `move_to(drone_id="bravo", x=3.312, y=117.590)`

**Tool Results (green, labeled "RSLT"):**

- Server responses showing success/failure
- Example: `{"status": "moving", "current_position": [3.314, 117.591], "eta_ticks": 12}`

**Assistant Messages (success green):**

- High-level summaries of what just happened
- Example: `"Bravo is now en route to Zone-2. Charlie is scanning Zone-1. Alpha remains at base as reserve."`

**How to Narrate the CoT Log:**

> "I want you to focus here [point to the CoT log]. This is where the breakthrough is. In our competitors' systems, when a drone moves or scans, it's a black box. The coordinator doesn't know why. Did the system mess up? Is something wrong? Should we abort?
>
> Here, every decision is explained. The agent says, 'This is my reasoning. This is the tool I'm calling. Here's the result. Now here's my next step.' This transparency is what gives rescue coordinators confidence in the system, especially in life-or-death scenarios."

**Technical point:**

> "This chat interface is built with React. Messages are streamed in real-time via SSE. The `ChatPanel` component listens to the mission state, appends messages as they arrive, and auto-scrolls to the latest. No lag. No buffering. The reasoning is visible instantly."

---

#### 4. The Progress Indicators (Top Left)

> "On the mission control panel at the top, you're seeing aggregate metrics:"

**Tick Counter:**

> "The 'Tick' counter increments with each simulation step. This is our heartbeat. In a real system, this would be elapsed time. Right now, it's discrete steps."

**Scanning Coverage:**

> "The 'Scanning Coverage' percentage shows what fraction of the disaster zone has been thermally scanned. As drones execute thermal_scan(), this percentage increases. The progress bar below it fills in real-time."

> "When this number reaches 100%, all survivors in the disaster zone have been detected and their locations broadcast. The mission enters the endgame phase."

---

### What Success Looks Like:

> "Here's what we're demonstrating:
>
> 1. **Autonomous Planning** — The agent decomposes a high-level goal ('find all survivors') into low-level actions (move drone, scan zone, check battery, return to base) without any human input after launch.
> 2. **Dynamic Resource Management** — Battery constraints are real. Drones can't just fly forever. The agent sees battery dropping, decides which drones should continue and which should return home. It's optimizing for survival — finding the maximum number of survivors before power fails.
> 3. **Adaptive Replanning** — If a survivor appears in an unexpected location, or if a drone's battery drops faster than expected, the agent recalculates. It doesn't stick to its original plan blindly.
> 4. **Transparent Decision-Making** — Every decision is explained before execution. Rescue coordinators can see the reasoning and trust the system.
> 5. **Resilient Architecture** — All communication goes through MCP. The agent doesn't hard-code drone IDs. New drones can be added mid-mission. Drones can fail, and the system re-balances. This is edge autonomy."

---

### Expect to See:

#### Early Phase (First 2 minutes):

- All 5 drones leave base and spread to different zones
- Battery levels drop from ~80% to ~50% as they move
- Coverage percentage rises from 0% to ~20%
- CoT log fills with planning messages and tool calls

#### Mid Phase (Minutes 2-5):

- Some drones complete their assigned zones and return to base
- Agent assigns remaining drones to remaining uncovered zones
- Battery management becomes critical — some drones sitting idle to preserve power
- Survivor detections appear on map as coverage expands
- Coverage percentage reaches 50-80%

#### End Phase (Final 3 minutes):

- Last drones complete final scans
- All drones return to base
- Cooling down phase — waiting for agent to confirm all survivors detected
- Coverage reaches 95%+
- Chat log shows final reasoning and mission end statement

---

## PART V: MISSION END & ANALYSIS [8:00 - 9:00]

### When Mission Completes

> "The mission has ended. All survivors have been detected or the coverage is sufficiently comprehensive that rescue operations can begin. The system transitions to the **ended** phase."

**Show on screen:**

- Sidebar switches to `EndedPanel`
- Map shows final state with all drones at base
- Coverage is complete (or as complete as the agent deemed safe)
- Survivor markers are all on the map
- Zone polygons are all complete (grayed or faded)

---

### Results Analysis

> "Let me show you the summary. Look at the CoT log one more time."

**Recap what the log shows:**

- Total survivors detected
- Total drones used
- Final battery levels (should be 10-30% for drones that engaged, unused drones should still have 70%+)
- Zones covered in what sequence
- Any adaptations the agent made mid-mission

> "This log is exportable and auditable. In a real disaster response, these logs are critical. They prove:
>
> 1. **Efficiency** — How many survivors were found per unit time/battery?
> 2. **Safety** — Did any drone's battery hit critical levels? Were they recalled in time?
> 3. **Coverage** — Which areas were scanned thoroughly? Which need follow-up?
> 4. **Decision Quality** — Did the agent's reasoning make sense?
>
> All of this is in the chat log."

---

### Technical Summary

> "Let me wrap up what you've just seen by highlighting the key technologies:"

**React & TypeScript:**

> "The entire UI — every button, every card, every animation — is React. TypeScript ensures every component is type-safe. This matters because a runtime error in a disaster response system could cost lives. When rescue coordinators interact with buttons, drag zone polygons, or read drone status, they're interacting with React components that have been checked for type correctness at build time."

**Leaflet.js:**

> "The map is Leaflet. It's rendering vector graphics (drones, survivors, zones, coverage) directly on a canvas. It doesn't need the internet to keep working. All the tile data and geometric rendering happen client-side. This is how we survive a communication blackout."

**Chain-of-Thought in the UI:**

> "The reasoning is visible because we designed the mission state and the chat interface to surface it. Every tool call is logged. Every result is displayed. React's reactivity makes this possible — as state updates, the chat panel automatically shows the new messages."

**Real-time Synchronization:**

> "The map updates 30+ times per second. The drone cards update their battery levels. The coverage percentage ticks upward. All of this is event-driven via SSE (Server-Sent Events). React receives updates, updates state, and re-renders only affected components. This is why the UI stays responsive even under high data flow."

---

## PART VI: CLOSE & TRANSITION TO Q&A

> "What you've just seen is a working implementation of the study case requirements:
>
> - **Autonomous Mission Planning** — ✓ The agent decomposed a high-level goal into tool calls
> - **MCP Tool Integration** — ✓ Every move_to, get_battery_status, thermal_scan went through the protocol
> - **Strategic Resource Management** — ✓ Battery constraints were real and the agent adapted
> - **Real-time Tool Discovery** — ✓ The agent discovered drones dynamically, not from hard-coded IDs
> - **Chain-of-Thought Reasoning** — ✓ Every decision was explained and visible
>
> The frontend is the command center. It makes that reasoning and those results visible to human rescue coordinators. React keeps it fast. TypeScript keeps it safe. Leaflet keeps it offline-capable.
>
> When the world goes dark, this system doesn't just keep running — it becomes the world."

---

## PRESENTER TIMING & NOTES

| Section               | Duration | Focus                                                                                      |
| --------------------- | -------- | ------------------------------------------------------------------------------------------ |
| Setup Phase           | 1:00     | Calm, methodical. Show the base and boundary placement.                                    |
| Zone Definition       | 0:45     | Deliberate clicks. Show zone colors on map.                                                |
| Mission Briefing      | 0:30     | Explain the three standardized tools and the discovery concept.                            |
| **Mission Execution** | **6:00** | This is the centerpiece. Let the agent work. Narrate what's happening on all four screens. |
| End & Analysis        | 1:00     | Recap results. Show the auditable log.                                                     |

**Total: 9 minutes**

---

## Narration Style During Execution

- **Let silence breathe.** Don't constantly narrate. Sometimes just watch the drones move and let the audience absorb the motion.
- **Point, don't read.** Use your cursor to point at things on the map or in the chat log. Don't read everything verbatim.
- **Celebrate milestones.** When the first survivor is detected, acknowledge it: _"First detection."_ When coverage hits 50%, note it: _"Halfway home."_
- **Flag surprises.** If the agent makes an unexpected decision, call it out: _"Notice that Bravo is staying in reserve instead of joining the scan. That's the agent being strategic about battery."_
- **Relate to the scenario.** Every technical detail connects to the rescue mission. Don't say, "React's virtual DOM"; say, "The UI stays responsive even as thousands of data points flow in per second — that's critical when rescue coordinators need instant visibility."

---

## If Things Go Wrong During Demo

**Drone stops moving:**

> "If a drone stalls, it's likely hitting a battery threshold or encountering an unexpected boundary. The agent is being cautious — it recalculates before proceeding. This is safe-by-default behavior."

**Coverage not increasing:**

> "The thermal_scan tool might be returning a large area in a single call, so visually it jumps rather than fills smoothly. The important thing is that the coverage percentage is rising and survivors are being detected."

**Mission takes longer than expected:**

> "The agent is optimizing for thoroughness over speed. It's ensuring coverage is complete rather than rushing. In a real scenario, this is the correct trade-off."

**Chat log becomes hard to read:**

> "There's a lot of information streaming in. Focus on the color coding: purple for thinking, cyan for tool calls, green for results. The pattern is: think → call → result → act."

---

## Key Points to Drive Home

1. **MCP is mandatory.** Every action goes through the protocol. No shortcuts. This is what makes the system auditable and resilient.

2. **The agent reasons, not executes blindly.** Chain-of-Thought is visible and explains every decision.

3. **Battery is the constraint.** All decisions are filtered through resource management. The agent knows what it can and can't do.

4. **The UI makes it human.** React, TypeScript, and Leaflet combine to create a command center that rescue coordinators can trust.

5. **This solves the study case.** In the first 72 hours after a disaster, when the internet is down and rescue systems have failed, this system keeps searching and finding survivors.
