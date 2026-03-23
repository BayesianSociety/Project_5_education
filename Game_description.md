

Below is a **copy-paste, extremely detailed “build prompt”** you can give to an implementation agent (Codex / GPT / dev team) to recreate the **same style of educational coding puzzle game** described in the teacher guide and the activity page, with an added **SQLite event + movement tracking database** and a polished, professional UI. It mirrors the key interaction model: **puzzle-based progression**, **drag-and-drop block coding workspace**, **run/play button**, **“Oops” + hint feedback**, and learning goals around **sequencing, loops, and conditionals**. ([Tynker.com][1])

---

## Master Build Prompt: “Pet Vet Coding Puzzles” (Block-Coding Educational Game + SQLite Telemetry)

### 0) Your Role and Output Requirements

You are a senior full-stack engineer, game designer, and learning-experience designer.

You will build a complete, production-quality, browser-based educational coding game that replicates the gameplay structure and user experience of a beginner Hour-of-Code style puzzle activity:

* Beginner-friendly puzzle progression.
* A story theme: a busy day at a pet veterinary clinic, where the player helps pets through checkups by writing simple programs.
* A visual programming workspace where the user drags commands (“blocks”) from a library into a connected sequence under an “on start” header.
* A Play/Run button that executes the program and animates the pet and scene.
* If the program is incorrect, show an “Oops” message and a helpful hint.
* Gradual introduction of: sequencing, loops, and conditionals.
* Exactly **17 puzzles** (plus optional non-puzzle story/selection screens if desired), designed to take about **30 minutes** for a typical learner. ([Tynker.com][1])

You must produce:

1. A complete working application (frontend + backend).
2. A SQLite database schema and a robust event logging system that records **all movements and all game events** (details below).
3. A clean, professional, pleasing UI with consistent typography, spacing, iconography, and accessible colors.
4. Built-in “teacher/observer” analytics pages (local-only is fine) that query SQLite to show what happened.

Do **not** use proprietary brand characters or logos. Create an original, friendly veterinarian mentor character and original pet characters, while keeping the *same kind of experience*.

---

## 1) Product Definition (What We Are Building)

### 1.1 Game Summary

Create a puzzle-based coding game called **“Pet Vet Coding Puzzles”**.

The player is an assistant vet. Each puzzle is a single “scene” in the clinic (waiting area, hallway, exam room, treatment corner). The player writes a tiny program using blocks to guide pets, interact with objects, and complete objectives such as:

* Walk to a target spot (exam table / scale / bed).
* Pick up an item (toy, bone, bandage).
* Give a treatment (clean, bandage, medicine).
* Respond to conditions (if pet is itchy, then apply ointment; else give treat).
* Use loops to repeat steps (walk 3 steps; repeat brush action until clean).

The experience must emphasize:

* **Sequencing**: order of actions matters. ([Tynker.com][1])
* **Loops**: repeat actions a fixed number of times or until a condition. ([Tynker.com][1])
* **Conditionals**: if/else based decisions. ([Tynker.com][1])

### 1.2 Target Audience and UX Constraints

* Beginner learners (reading required).
* Very low friction: runs in a modern browser, no downloads.
* Large buttons, clear labels, friendly tone, strong affordances.
* Hints should guide without giving away full solutions.

---

## 2) Core Gameplay Loop

### 2.1 Puzzle Structure

Each puzzle contains:

* A scene background (clinic room).
* One or more characters: at least one pet and optionally a mentor.
* Objects (e.g., bone/toy/bandage) and target locations (e.g., exam table).
* A goal statement: “Get the puppy to the exam table” / “Help the kitten stop itching.”
* A limited command library for that puzzle (only relevant blocks appear in the left library). ([Tynker.com][1])
* A coding area that starts with a fixed “on start” block (root event). ([Tynker.com][1])

Success conditions:

* The pet reaches goal position and required interactions are completed.
* The program finishes without errors.
* The puzzle is marked completed and the next puzzle unlocks.

### 2.2 The Workspace (Must Match the Interaction Model)

Implement a workspace with these exact conceptual parts:

**Left Panel: Command Library**

* Shows the available blocks for the current puzzle only.
* Blocks are grouped into categories:

  * Movement
  * Actions
  * Control (loops)
  * Logic (conditionals)
  * Sensing (checks like “is itchy?”)
* Blocks are draggable.

**Right Panel: Active Code Area**

* Contains:

  * A fixed root “On Start” block.
  * A vertical sequence where blocks snap together.
* Blocks must visually “connect” so it’s obvious what will run.
* Disconnected blocks do not execute, and the UI must warn about it. ([Tynker.com][1])

**Bottom/Corner Controls**

* A large **Play** button that runs the code and hides/minimizes the workspace overlay during animation, matching the described behavior (“workspace disappears and events follow commands”). ([Tynker.com][1])
* A **Reset** button to reset the scene to initial state.
* A **Step** button (optional) for debugging (execute one block at a time).
* A speed toggle (slow/normal/fast).

**Feedback**

* If the result is incorrect, show:

  * A modal/toast: “Oops!”
  * A helpful hint tailored to that failure.
  * Highlight the first likely incorrect block (best-effort heuristic).
    This “Oops + hint” pattern is required. ([Tynker.com][1])

### 2.3 Block Languages

You must support:

* Visual blocks as the primary input.
* A “Show Code” toggle that displays the equivalent text code representation (read-only is fine).
  Inspiration: the original environment mentions switching among blocks and text languages. You may implement read-only code view for simplicity, but the toggle must exist. ([Tynker.com][1])

---

## 3) Level Pack Specification (17 Puzzles)

### 3.1 Difficulty Curve

Design 17 puzzles increasing in complexity:

**Puzzles 1–5 (Sequencing Basics)**

* Only “walk” and a small number of steps.
* Single objective: reach a location; simple path with dots/tiles.
* Introduce “pick up” action in puzzle 4 or 5.

**Puzzles 6–10 (Loops)**

* Introduce “repeat N times” to reduce block count.
* Puzzle includes a longer hallway/sequence of tiles.
* Add repeated actions: “brush” 3 times, “clean” 2 times, “walk” repeated.

**Puzzles 11–17 (Conditionals + Mixed Concepts)**

* Introduce a sensor condition: “pet has sniffles?” “pet is itchy?” “pet has boo-boo?”
* Require if/else: apply correct treatment based on symptom.
* Mix loops + conditionals: loop through stations; treat until condition resolved.

### 3.2 Level Data Format

All puzzles must be defined in data (JSON) so new puzzles can be added without code changes.

Each puzzle JSON must include:

* `id` (1..17)
* `title`
* `storyText` (mentor speech bubble)
* `goalText`
* `scene` (background id)
* `grid` definition (tile size, walkable tiles, obstacles)
* `entities`:

  * pet (start position, sprite, state flags like `itchy`, `sniffles`, `injured`)
  * objects (positions, type)
  * targets (positions, type)
* `availableBlocks` list
* `constraints`:

  * maxBlocks (optional)
  * requiredBlocks (optional)
* `successCriteria`:

  * reach position
  * collect object(s)
  * perform action(s) in order or at location
* `hintRules`:

  * failure mode -> hint text mapping

---

## 4) Animation + Execution Engine

### 4.1 Execution Model

* Compile the connected block graph under “On Start” into an executable instruction list / AST.
* Execute instructions deterministically.
* Provide a runtime that can:

  * Move a character step-by-step with tweened animation.
  * Wait for animations to complete before next instruction (or queue them).
  * Evaluate conditions using the current world state.
  * Repeat loops with a strict maximum-iteration safety cap (to prevent infinite loops).

### 4.2 Movement Rules

* Use a simple grid/tile movement system.
* Each `walk()` moves 1 tile forward in the pet’s facing direction.
* Include `turnLeft()` and `turnRight()` in later puzzles (optional but recommended).
* Collisions:

  * If a move hits an obstacle, stop and mark run as failed with a specific error type.
  * Log collision events to SQLite.

### 4.3 World State + Interactions

Track:

* Pet position (x,y), facing direction, animation state.
* Pet symptoms: itchy/sniffles/injured booleans.
* Object inventory: items picked up.
* Station interactions: exam table visited, medicine applied, bandage applied, etc.

### 4.4 Failure Detection and Hints

On failure, compute a `failureReason`:

* Did not reach target.
* Wrong item used.
* Wrong order.
* Hit obstacle.
* Condition not handled (e.g., pet itchy but no ointment applied).

Then show:

* “Oops!” message
* A hint referencing the failureReason.
  This mirrors the described behavior of showing an “Oops” message with a helpful hint when code does not match the solution. ([Tynker.com][1])

---

## 5) UI / Visual Design Requirements (Professional and Pleasing)

### 5.1 Layout

Three main regions:

1. **Top Bar**

   * Game title on left.
   * Current puzzle indicator: “Puzzle 6 of 17”.
   * Progress bar.
   * Sound toggle.
   * Settings (accessibility, text size).

2. **Main Canvas Area**

   * 2D scene with soft, modern illustration style.
   * Speech bubble area near mentor character for story prompts.
   * Goal banner: short, clear.

3. **Workspace Overlay**

   * Slides in or overlays the left side; can be collapsed.
   * Left: block library.
   * Right: code assembly area.
   * Bottom-right: Play button (big, primary).

### 5.2 Visual Style

* Use a cohesive pastel palette, with high contrast for text.
* Consistent rounded corners, subtle shadows, and spacing.
* Friendly icons for block categories.
* Smooth micro-interactions:

  * Block snap animation.
  * Button hover states.
  * Gentle success celebration.

### 5.3 Accessibility

* Keyboard navigation for major controls.
* Text-to-speech optional for goal text.
* Colorblind-safe contrast checks.
* No essential info conveyed by color alone.

---

## 6) SQLite Database: Track Movements and All Events

### 6.1 Requirements

Add a SQLite database that records:

* Every program run.
* Every block execution step.
* Every movement step (tile-to-tile).
* Every interaction event (pickup, treat, bandage, collision).
* Every UI event (Play clicked, Reset clicked, Hint shown, Puzzle completed).
* Every outcome (success/failure + reason).
* Time spent in puzzle, number of attempts, number of edits.

This is non-negotiable: “track movements and all events that take place in the game.”

### 6.2 Architecture for Telemetry

* Backend owns SQLite file.
* Frontend sends events to backend via HTTP endpoint `POST /api/events`.
* Events are buffered on the client and flushed:

  * Immediately for critical events (run start, run end).
  * Debounced for high-volume events (block dragging, cursor movement) — but **movement steps and block execution steps must not be dropped**.
* Backend writes events with transaction batching for performance.

### 6.3 Database Schema (Exact Tables to Implement)

**Table: `users`**

* `id` TEXT PRIMARY KEY
* `created_at` INTEGER NOT NULL
* `display_name` TEXT

**Table: `sessions`**

* `id` TEXT PRIMARY KEY
* `user_id` TEXT REFERENCES `users(id)`
* `started_at` INTEGER NOT NULL
* `ended_at` INTEGER
* `user_agent` TEXT
* `locale` TEXT

**Table: `puzzles`** (static metadata cached in DB for reporting)

* `id` INTEGER PRIMARY KEY (1..17)
* `title` TEXT NOT NULL
* `concepts` TEXT NOT NULL  (comma-separated: sequencing, loops, conditionals)

**Table: `attempts`**
Represents one press of Play in a puzzle.

* `id` TEXT PRIMARY KEY
* `session_id` TEXT REFERENCES `sessions(id)`
* `user_id` TEXT REFERENCES `users(id)`
* `puzzle_id` INTEGER REFERENCES `puzzles(id)`
* `started_at` INTEGER NOT NULL
* `ended_at` INTEGER
* `result` TEXT CHECK(result IN ('success','failure','aborted')) NOT NULL
* `failure_reason` TEXT  (nullable)
* `code_snapshot_json` TEXT NOT NULL  (serialized block AST / graph)
* `block_count` INTEGER NOT NULL
* `execution_steps` INTEGER NOT NULL
* `client_version` TEXT

**Table: `events`**
Generic event stream for everything (UI + gameplay).

* `id` TEXT PRIMARY KEY
* `session_id` TEXT NOT NULL
* `user_id` TEXT
* `attempt_id` TEXT
* `puzzle_id` INTEGER
* `ts` INTEGER NOT NULL
* `type` TEXT NOT NULL   (examples below)
* `payload_json` TEXT NOT NULL

Event type examples you must emit:

* `ui.play_clicked`
* `ui.reset_clicked`
* `ui.hint_shown`
* `ui.block_added`
* `ui.block_removed`
* `ui.block_reordered`
* `run.started`
* `run.ended`
* `exec.block_started`
* `exec.block_finished`
* `move.step` (tile movement)
* `move.turn`
* `world.pickup`
* `world.treat_applied`
* `world.collision`
* `puzzle.completed`

**Table: `movements`**
A specialized table to make “movement” queries fast.

* `id` TEXT PRIMARY KEY
* `attempt_id` TEXT NOT NULL REFERENCES `attempts(id)`
* `ts` INTEGER NOT NULL
* `entity` TEXT NOT NULL  (e.g., 'pet')
* `from_x` INTEGER NOT NULL
* `from_y` INTEGER NOT NULL
* `to_x` INTEGER NOT NULL
* `to_y` INTEGER NOT NULL
* `direction` TEXT  (N/E/S/W)
* `cause` TEXT NOT NULL  (e.g., 'walk', 'teleport', 'reset')
* `blocked` INTEGER NOT NULL DEFAULT 0  (1 if collision prevented move)

**Table: `puzzle_progress`**
Latest completion state per user.

* `user_id` TEXT NOT NULL
* `puzzle_id` INTEGER NOT NULL
* `completed_at` INTEGER
* `best_attempt_id` TEXT
* PRIMARY KEY (`user_id`, `puzzle_id`)

### 6.4 Analytics Views / Pages (Must Build)

Create a protected or local-only “Analytics” area that queries SQLite and shows:

**Dashboard**

* Total sessions, total attempts, success rate.
* Average attempts per puzzle.
* Average time per puzzle.

**Puzzle Detail Page**

* Attempt timeline for a selected puzzle.
* For each attempt:

  * Code snapshot (render blocks read-only).
  * Result + failure reason.
  * Execution steps.
* A map replay:

  * Reconstruct pet path from `movements` table and animate it.

**Event Stream Viewer**

* Filter by session, puzzle, attempt.
* Show event type and payload JSON in a readable layout.

---

## 7) Tech Stack (Recommended, but you may choose equivalents)

Implement as a web app:

### 7.1 Frontend

* TypeScript.
* React (or equivalent).
* Canvas rendering (PixiJS or HTML5 Canvas) or a lightweight 2D engine.
* Drag-and-drop block UI:

  * Either a custom block UI OR Blockly (acceptable if you style it heavily to look polished and game-like).

### 7.2 Backend

* Node.js + TypeScript.
* Express/Fastify for HTTP.
* SQLite using a reliable library (better-sqlite3 or sqlite3).
* API routes:

  * `POST /api/session/start`
  * `POST /api/session/end`
  * `POST /api/events/batch`
  * `GET /api/analytics/*`

---

## 8) Detailed Functional Requirements (No Handwaving)

### 8.1 User Flow

1. **Landing Screen**

   * Title, start button, optional “How to Play”.
2. **Puzzle Map / Level Select**

   * 17 nodes, lock/unlock progression.
3. **Puzzle Screen**

   * Scene loads.
   * Goal shown.
   * Workspace overlay opens with limited blocks for that puzzle.
4. User drags blocks into code area.
5. User presses Play.
6. Code executes; animations play.
7. On success:

   * Celebration, “Next puzzle” button.
   * Log completion and update progress.
8. On failure:

   * “Oops!” + hint.
   * Reset option.
   * Encourage trying again.

### 8.2 Logging (Must Be Comprehensive)

Every time any of these happens, you must log an event:

* Puzzle opened/closed.
* Block added/removed/reordered/changed parameter.
* Play clicked.
* Run started / ended.
* Every block execution start/finish.
* Every movement step.
* Every collision.
* Every item pickup.
* Every treatment action.
* Hint shown (with hint id and reason).
* Puzzle completed.

Additionally:

* Save a complete `code_snapshot_json` at Play time into `attempts`.

---

## 9) Quality Bar

* Smooth animations, no jank.
* No lost events: movement steps and execution steps must be reliably persisted.
* Clear separation between:

  * Puzzle data
  * Execution engine
  * Rendering/animation
  * Telemetry logging
* Clean UI polish: consistent spacing, typography, button hierarchy.

---

## 10) Acceptance Tests (You Must Satisfy)

1. The game contains exactly 17 playable puzzles and a clear progression. ([Tynker.com][1])
2. Each puzzle has a block library (left) and active code area (right) with an “On Start” root. ([Tynker.com][1])
3. Play runs the code, animates the scene, and incorrect solutions display “Oops!” + hint. ([Tynker.com][1])
4. SQLite database is created automatically on first run.
5. A completed run produces:

   * An `attempts` row
   * Many `events` rows
   * Many `movements` rows (if movement happened)
6. Analytics pages can replay a run’s movement path from SQLite.

---

## 11) Source-Inspired Notes (Ground Truth From the Link)

Use these details as constraints because they are explicitly stated in the referenced materials:

* The activity is designed for self-directed learning and consists of puzzles that increase in complexity. ([Tynker.com][1])
* The workspace includes a command library (left) and an active code area (right) where blocks are dragged and connected under “on start.” ([Tynker.com][1])
* Running incorrect code triggers an “Oops” message with a helpful hint. ([Tynker.com][1])
* The learning concepts are sequencing, loops, and conditionals. ([Tynker.com][1])
* The published activity describes a busy day at a pet vet, guiding pets into an exam room and addressing sniffles, boo-boos, and itches (use as thematic inspiration, but keep characters original).

---


[1]: https://www.tynker.com/hour-of-code/barbie-pet-vet-guide.pdf "Hour of Code Barbiea Pet Vet Teachers Guide 2022 pdf | Tynker"
