# Project Description

READ THIS FILE IN FULL BEFORE IMPLEMENTING!!!

## Project Summary

Build a browser-based educational coding game called `Block Coding Puzzles`.

The product is a beginner-friendly puzzle game in which the player acts as an assistant and solves programming puzzles by assembling visual code blocks. The game must teach sequencing, loops, and conditionals through puzzle-based progression. It must also include SQLite-backed telemetry that records all gameplay and UI events, including movement steps.

The experience must be original in assets and characters. It may take thematic inspiration from https://www.tynker.com/hour-of-code/barbie-pet-vet learning activity, but it must not use proprietary brand characters or logos.

## Scope

This run is expected to produce a complete working application with:

- a flashy frontend game UI with game assets from a local repository
- a backend that persists telemetry to SQLite
- 3 playable puzzles
- a block-based workspace with an `On Start` root
- execution, reset, and failure feedback flows
- analytics pages that read from SQLite

In scope:

- puzzle progression
- drag-and-drop block coding workflow
- puzzle execution and animation
- telemetry capture for gameplay and UI activity
- local analytics and replay views

Out of scope unless needed for implementation:

- use of proprietary third-party characters or branding
- native apps
- multiplayer
- cloud hosting requirements

## Functional Requirements

### Core Game Loop

The application must provide:

- a landing screen with a start action and how-to-play guidance
- a puzzle map or level-select view with 3 puzzles and lock/unlock progression
- a puzzle screen that loads one scene at a time
- a workspace where the player assembles a program and runs it
- success and failure handling for each run

Each puzzle must include:

- a scene with a background from the game assets repository 
- at least one game actor
- objects and target locations as required by the puzzle
- a goal statement
- a limited set of available blocks for that puzzle
- a code area with a fixed `On Start` root block

Success requires:

- the required objective is completed
- the program finishes
- the puzzle can be marked complete and progression can advance

### Workspace And Interaction Model

The workspace must include:

- a command library on the left
- an active code area on the right
- visually connected blocks under a fixed `On Start` root
- a warning when blocks are disconnected and therefore will not execute

The command library must support categories for:

- movement
- actions
- control / loops
- logic / conditionals
- sensing

The run controls must include:

- `Play`
- `Reset`
- a speed toggle

all controls must be very visible, no dark colors

When the user presses `Play`, the program must execute and animate the scene. During execution, the workspace should hide or minimize enough for the animation to be visible.

### Failure Feedback

Incorrect solutions must show:

- an `Oops!` message
- a helpful hint tied to the failure reason

Failure reasons should cover at least:

- target not reached
- wrong item used
- wrong order
- obstacle collision
- required condition not handled

### Concepts And Puzzle Progression

The game must teach these concepts:

- sequencing
- loops
- conditionals

The 3 puzzles must increase in complexity:

- puzzle 1 focus on sequencing basics
- puzzle 2 introduce loops
- puzzle 3 introduce conditionals and mixed logic

### Puzzle Data

Puzzles must be data-driven so additional puzzles can be added without changing core game logic.

Each puzzle definition must include enough data to represent:

- id
- title
- story text
- goal text
- scene identifier
- grid definition
- entities
- available blocks
- constraints
- success criteria
- hint rules

### Execution Engine

The game runtime must:

- compile the connected block sequence or graph under `On Start` into executable instructions
- execute instructions deterministically
- animate movement step by step
- wait for or sequence animation completion appropriately
- evaluate conditions from world state
- prevent infinite loops with a safety cap

Movement and world logic must support:

- tile-based movement
- facing direction
- optional turning actions
- collision handling
- item pickup
- treatment actions

### Code View

The game must provide a `Show Code` toggle that displays an equivalent text representation of the visual program. Read-only text output is acceptable.

## Telemetry And Data Requirements

Telemetry is mandatory. The system must record all gameplay and UI events that occur in the game, including movement.

The backend must own a SQLite database. The frontend must send event data to the backend through HTTP endpoints. High-volume UI events may be buffered or debounced, but movement steps and block execution steps must not be dropped.
Both backend and frontend must fit perfectly together.

The SQLite design must include tables for:

- `users`
- `sessions`
- `puzzles`
- `attempts`
- `events`
- `movements`
- `puzzle_progress`

The telemetry model must support recording:

- session lifecycle
- puzzle open and close events
- play and reset events
- block edits and reordering
- run start and end
- block execution start and finish
- every movement step
- turns
- collisions
- item pickups
- treatment actions
- hints shown
- puzzle completion
- run outcome including success or failure and failure reason
- code snapshot at play time

Analytics must include:

- a dashboard with overall aggregates
- puzzle detail views
- per-attempt history
- readable event stream inspection
- replay of movement paths from stored movement data

## Technical Constraints

Required technical direction from the source brief:

- the starting point is node version v24.11.0 and npm version 11.6.1
- all used modules should be compatible with the node and npm versions
- frontend and backend must be implemented in TypeScript using Next.js 16.x only
- the block editor must provide a drag-and-drop UI, implemented either as a custom system or with Blockly, with substantial visual styling to match the product
- backend functionality must be delivered through Next.js server capabilities, including HTTP API routes for session, event, and analytics flows
- persistence must use SQLite by using better-sqlite3, staying on the latest stable compatible with Node v24
- the application architecture should remain browser-based, with a unified Next.js codebase handling UI, game logic integration, telemetry ingestion, analytics reads, and SQLite-backed data access

The application must run in a modern browser and should require no downloads for end users beyond normal web access.

Accessibility requirements:

- keyboard navigation for major controls
- color contrast suitable for readability
- no essential information conveyed by color alone
- optional text-to-speech for goal text

## API And Data Expectations

The backend API must support endpoints for:

- starting a session
- ending a session
- batching event submission
- reading analytics data

The source brief explicitly names these endpoint shapes:

- `POST /api/session/start`
- `POST /api/session/end`
- `POST /api/events/batch`
- `GET /api/analytics/*`

## User Experience Requirements

The interface should be polished, consistent, and readable, with:

- a top bar showing title and puzzle progress
- a main scene area
- a workspace overlay or panel
- large primary controls
- clear visual grouping
- smooth interactions
- game assets such as background and actors should be used from a local repository

The visual language should be friendly and professional rather than generic or placeholder-like.

## Repository And Artifact Expectations

This brief is the canonical input for a run of the repository’s multi-agent workflow.

The implementation plan must produce concrete relative file paths for all owned work and all required outputs. The final implementation must include:

- application source for the frontend
- application source for the backend
- puzzle data definitions
- SQLite schema or initialization logic
- analytics functionality
- any required configuration needed to run the application

The exact file layout is not fixed by this brief. The planner must choose concrete paths that fit the implemented stack and keep ownership boundaries unambiguous.

## Validation Requirements

The implementation must satisfy these acceptance criteria:

1. The application contains exactly 3 playable puzzles with clear progression.
2. Each puzzle has a left-side block library and right-side active code area under an `On Start` root.
3. `Play` executes the code and animates the scene.
4. Incorrect solutions show `Oops!` and a helpful hint.
5. SQLite is created automatically on first run.
6. A completed run persists an `attempts` row, `events` rows, and `movements` rows when movement occurs.
7. Analytics can replay a run from stored movement data.

Validation for the implementation should include:

- build checks for the chosen frontend and backend stack
- runtime checks that the app starts successfully
- verification that database initialization occurs automatically
- verification that telemetry rows are written for runs and movements
- verification that analytics can read stored run data

The exact shell commands are not fixed in this brief and should be chosen to match the actual implementation.


## Visual Style Requirements

The product must present a clear, original visual identity suited to a beginner-friendly educational game.

The visual direction must be:

- cartoon-style
- polished and beautiful rather than placeholder-like, use shades of pink and violet 
- use local repo for game assets
- friendly, warm, and appealing to a broad child-and-family audience
- professional in finish, with consistent art direction across gameplay screens, UI, and analytics views

The art and scene presentation must include:

- original characters and environments
- colorful, high-contrast scene composition that remains easy to understand during play
- visually distinct puzzle elements so goals, hazards, targets, and interactable objects are immediately recognizable

The gameplay presentation must prioritize readability as well as charm:

- the player character, obstacles, items, and destinations must remain visually clear at all times
- animation and effects must support gameplay feedback without obscuring puzzle state
- visual cues for success, failure, collision, pickup, treatment, and conditional state changes must be easy to notice

The rendering approach must support attractive, modern 2D presentation:

- the game should use WebGL-based 2D rendering capable of smooth animation, layered scenes, particles, lighting accents, and other effects appropriate to a polished cartoon experience
- the chosen rendering stack must support high-quality sprite animation and transitions in a modern browser

The user interface must visually match the game world:

- block coding panels, puzzle HUD, menus, and overlays must share the same cohesive visual language as the scenes
- the interface must feel intentionally designed rather than generic default tooling
- substantial styling is required if Blockly or another third-party block system is used

## Asset Production Requirements

Visual asset creation for the project will be provided in a local repository rather than generated by the implementation agent.

The implementation must assume that:

- the user will provide graphical assets for the game, including character sprites, objects, and scene backgrounds
- sprite and background assets will be delivered as `PNG` files unless a specific exception is explicitly provided
- the user will also provide a separate drawing or layout reference file that shows how the supplied assets should be arranged within a scene or background
- read the layout reference very carefully before creating the frontend
- place the assets in the same way as in the layout reference, and start creating the UI from this starting position
- this initial setup will be given only for the first level
- extraploate the initial setup to next levels

The supplied drawing or layout reference must be treated as the initial composition guide for implementation:

- it must be used as the basis for placing backgrounds, sprites, props, targets, obstacles, and other scene elements into the game view
- it defines the intended starting visual arrangement of the scene unless gameplay requirements require a clear implementation adjustment
- it should be translated into the scene setup, puzzle data, coordinate placement, collision regions, and initial world state used by the game

The implementation workflow for scenes must therefore follow this order:
DO NOT SKIP THIS PART!!!

- ingest the provided background and sprite assets
- use the provided drawing or layout reference to assemble the initial scene composition
- align interactive objects and entity positions to that reference
- build the puzzle logic, movement rules, goals, and interactions on top of that assembled scene

Codex or any implementation agent must not assume responsibility for inventing final visual assets when external production assets are available.

If placeholders are required before final assets are supplied:

- placeholder usage must preserve the expected asset dimensions, anchor positions, and approximate scene layout so final asset replacement does not require major logic rewrites

### Asset Delivery Structure

To avoid ambiguity, the repository must use a fixed asset delivery structure for externally provided art files.

Provided assets should be placed in these locations:

- `public/assets/backgrounds/` for scene background `PNG` files
- `public/assets/sprites/` for character, pet, prop, object, and effect `PNG` files
- `design/layout_refs/` for user-provided scene layout drawings or placement reference files

The implementation must treat these directories as the canonical source locations for production art and placement references unless the brief is later revised with a different explicit structure.

###Logic & Asset Layout Breakdown

The plan defines a linear level flow where the assets are placed on a 2D plane. The "Background" text indicates the canvas area, and the arrows define the spacing and triggers between assets.

Spawn Point (Asset: main_character.png):Position: Far left of the screen (x = 0).Logic: This is the player's starting state.

The Walkway (Asset: place.png):Position: Distributed along the ground between the character and the goal.Logic: The "Move" arrows indicate these are traversal points. Based on the plan, there are two place.png assets before the obstacle and two place.png assets after the obstacle.

The Jump Hazard (Asset: obstacle.png):Position: Exact center of the level (x = 0.5).Logic: The "Jump" arc indicates this asset has a collision box that requires vertical movement to bypass. It separates the first two "place" markers from the last two.

The Goal (Asset: food.png):Position: Far right of the screen (x = 1.0).Logic: The "Success!" label indicates the win-state trigger. Touching this asset ends the level.

Asset Placement Prompt for the Agent
Objective: Arrange the four provided .png assets into a functional 2D game level layout on a white canvas. Do not render arrows or instructional text.
Assets: main_character.png, obstacle.png, place.png, food.png.

Placement Rules:
Horizontal Alignment: All assets must be aligned to a single horizontal "floor" line in the lower third of the frame.
Sequential Order (Left to Right):Place one main_character.png at the far left edge.Place two instances of place.png to the right of the character, spaced evenly to represent a walking path.Place one obstacle.png in the horizontal center of the layout. This serves as the mid-point hazard.Place two more instances of place.png to the right of the obstacle to continue the path.Place one food.png at the far right edge to serve as the finish line.
Spacing Logic:The distance between the character and the obstacle should be equal to the distance between the obstacle and the food.The place.png assets should fill the gaps created by the "Move" logic in the original plan.
