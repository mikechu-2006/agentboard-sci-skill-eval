# ScienceWorld Agent Skill (seed)

## Overview
You are acting in the ScienceWorld text simulator. Each turn you receive an observation and must reply with
exactly one admissible command. Tasks are short scientific procedures (boil / melt / freeze / measure /
identify / mix / grow / test conductivity ...).

**Output format**: Reply with exactly one line, starting with 'Action: ' followed by the chosen command -
for example 'Action: go to kitchen'. Output nothing else: no reasoning text, no <think> tags, no <action>
tags, no explanations.

## Command vocabulary (use the exact wording the environment offers)
- Navigation: `go to <room/object>`, `look around`, `look at <object>`, `look in <container>`
- Manipulation: `pick up <object>`, `put down <object>`, `move <object> to <container>`, `pour <a> into <b>`
- Containers/doors: `open <x>`, `close <x>`
- Devices: `activate <device>`, `deactivate <device>`, `use <device>`
- Measurement: `focus on <object>`, `read <device>`, `connect <a> to <b>`
- Inventory/hints: `inventory`, `check valid actions`

## General principles
1. `check valid actions` whenever a command is rejected; the environment only accepts its own templates.
2. `look around` after entering a new room; the room description lists what is reachable.
3. Inventory matters: many tasks require an object to be **in inventory** before acting on it.
4. Containers must usually be **opened** before their contents can be observed or used.
5. Temperature tasks: the target must reach a state (solid/liquid/gas), so keep the substance on the
   device until the observation reports the change; re-read the thermometer instead of guessing.
6. Electrical tasks may be unavailable (noElectricalAction simplification); check valid actions first.
7. Prefer short, direct procedures: locate -> acquire -> transform -> deliver/measure. Avoid repeating
   an action that just produced no change.

## Comparison / ranking tasks (longest-lived, ...-then-shortest-lived, which is hottest/hardest)
- These turn on a measurable property (e.g. lifespan). Evaluate EVERY plausible candidate before deciding: inspect or `focus on` each one in turn and read the value the observation/device reports. Record the values before acting.
- If the property is obtained from a device, get the candidate into position, `activate`/`use` the device, then `focus on` it and `read` to obtain the number instead of guessing.
- Once all values are known, execute the required ordered sequence of actions on the candidates (e.g. act on the max-valued item first, then the min-valued item). Never act on a candidate before its value is known, and re-check the ordering after each action.
- Chained goals ('X then Y') are satisfied in order: finish and report the first target, then continue to the second without restarting the search.

## Find / identify tasks (find-animal, find-non-living-thing, ...)
- The target is not visible at the start; it lives somewhere in the world. Explore systematically: `go to <room>`, then `look around` to list everything present, and move on to the next room if nothing matches.
- Inspect candidates in place with `look at <object>` (or `look in <container>` to reveal contents) and judge whether each one satisfies the goal (living vs non-living, animal vs plant, etc.).
- Once a candidate clearly matches, stop searching and act on / report that target; do not keep exploring or re-inspecting rejected candidates.
