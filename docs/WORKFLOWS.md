# Visual Workflow Builder / Flujos de trabajo

Open **Create / Crear** in the sidebar and then **Workflows / Flujos de trabajo** in its header (it is a button of its
own, not one of the eight templates). A workflow chains steps on a canvas; **Run** executes them in order, one live
log per step, and keeps a record of the run with measured times. Everything runs on this computer through the same
orchestrator, tools and permission prompts as the chat. Nothing is sent anywhere that a chat would not send it.

This document says what is built and how it is tested. What is not measured is listed at the end.

## The five node types

| Node | What it does | Ports |
| --- | --- | --- |
| **Input** | A value given when the run starts: text, number or a project file (see *File inputs*). It has a default. | out |
| **Specialist** | Sends an instruction to the orchestrator: `auto` (the router picks) or one specialist. The instruction is a template. | in, out |
| **Tool** | Calls one agent tool. Each argument may be a template. Arguments are checked against the tool's schema. | in, out |
| **Condition** | Tests the value that reaches it: *contains* text, matches a *regular expression*, or a *number* comparison (`< <= > >= == !=`). | in, true, false |
| **Output** | Saves the value to a project file (through the `write_file` tool) or shows it as an artifact. | in |

A condition passes on what it tested, unchanged, down the port that matched. A node with no input edge runs first.
`ask_user` and any tool that needs a person to answer or confirm cannot be used (the workflow has nobody to ask
mid-run); the catalog leaves them out and validation names them if an imported file uses one.

### Variables

A node name is also a variable. In a specialist prompt, a tool argument, a condition value, an output path or content or
an artifact title, `{{name}}` is replaced by the output of the input or earlier node called `name`, and `{{input}}` by
what arrives on the node's own `in` port (several live edges are joined with a blank line). `\{{` writes literal braces.
Names are letters, digits and `_`, not starting with a digit; `input` is reserved.

A variable must name an input or a node **upstream** of the one that uses it, and `{{input}}` needs an incoming edge.
A variable whose node was skipped (the other side of a condition) is an error on the node that uses it, never an empty
string.

### Edges

An edge goes from an output port to an input port. When a run goes, each edge is *live* (its source finished `ok`, and
for a condition went down that port), *neutral* (its source was skipped because a condition went the other way) or
*dead* (its source failed, was denied or was skipped for a dead edge). A node runs when none of its edges is dead and at
least one is live; otherwise it is skipped (`branch` or `upstream`). That lets the two branches of a condition join
again: the node after them runs with whichever side ran. Failure or denial in one branch does not stop the others.

## Validation

The same checks run in the browser while drawing (instant feedback for connections), on **Check**, before **Save**, and
again when a run starts. An invalid workflow cannot be saved. The server answers `422` with one problem per issue, each
with a code, the node and parameters; the UI shows a sentence per code in Spanish or English and marks the node.

| Check | Codes |
| --- | --- |
| At least one node, at most 60 nodes and 200 edges, valid ids and unique variable names | `no_nodes`, `too_big`, `node_id`, `node_type`, `node_name`, `name`, `format` |
| Input kind and default (a number input needs a number) | `input_kind`, `input_default` |
| Known specialist, non-empty prompt | `specialist_unknown`, `prompt_empty` |
| Known and usable tool; arguments exist, required ones are present, constant values have the schema's type | `tool_unknown`, `tool_unavailable`, `arg_unknown`, `arg_missing`, `arg_type` |
| Condition: known test, a value, a valid and not exponential regex (nested quantifiers such as `(a+)+` are refused), a number to compare | `condition_op`, `condition_value`, `condition_regex`, `condition_number`, `condition_compare` |
| Output: mode, a relative path inside the project (no `..`, absolute path or `workflows/` folder), content, format | `output_mode`, `output_path`, `output_content`, `output_format` |
| Edges: both nodes exist, not to itself, ports exist, no duplicate, **compatible ports** (a file cannot feed a condition), a condition has exactly one input | `edge_node`, `edge_self`, `edge_port`, `edge_duplicate`, `edge_type`, `edge_condition_inputs` |
| No cycle (the message names the nodes of the loop) | `cycle` |
| Every `{{variable}}` is well formed and resolves to an input or an upstream node | `var_syntax`, `var_input`, `var_unknown`, `var_upstream` |

Run inputs are checked before anything starts (`input_missing`, `input_number`, `input_file`).

Number tests accept `1,5` as 1.5 and take the first number found in a text (`Total: 42 EUR` is 42); a text with no
number fails the condition node with a clear error instead of guessing.

## Storage, versions, import and export

Workflows are plain JSON files in the project's own folder, so they travel with the project like any other file:

```
workflows/<id>/<NNNN>.json       one file per saved version, never rewritten; the newest is the workflow
workflows/<id>/runs/<run>.json   one record per run
```

Without a project the same layout is used in the SPIKE workspace folder. Every save writes a new version (`0001`,
`0002`, ...; the newest 50 are kept). `PUT` carries `base_revision`; if someone saved in between the server answers
`409 workflow_conflict` and the UI asks to reopen. The last 50 run records are kept. Files are read as untrusted:
size-capped (1 MB), symlinks refused, parsed with a normalizer that drops unknown fields, and a broken file is listed as
broken, never trusted. Everything is read and written as UTF-8.

**Export** downloads `<name>.spike-workflow.json` (`{"format": "spike-workflow", "version": 1, ...}` without the local id
or revision). **Import** validates it against this computer (a tool it lacks is a problem on that node) and saves it as a
new workflow with a new id. A file that cannot be saved as it is opens unsaved in the editor with the problems shown, so
it can be repaired. Because the files live in the project folder, project export and branches carry workflows too.

## Running

`POST /api/workflows/{id}/runs` validates again and starts the run in the background; the UI follows
`GET .../events` (Server-Sent Events, replayable with `?after=`). Nodes run in topological order. The cycle check is
this module's own (a cycle is a clear error naming its nodes); the order comes from the planner's `topological_levels`.
Nodes of one level run one after another, or together if the user's *parallel* setting is on.

- **Specialist steps** go through `Orchestrator.run` with the mode of the node (`auto`, or the specialist), exactly like
  a chat turn: routing, skills, memory settings, provider guards and the tools the specialist may call are the chat's.
- **Tool steps and file outputs** go through `spike.agent.loop.call_tool`, the function the chat's agent loop uses, with
  the shared permission broker. A tool whose policy is *ask* emits a `permission_request`; the UI shows the usual card
  (allow once / always / deny, answered through `POST /api/permissions/{id}`); *deny* policies and *ask* answered *deny*
  end that branch with a `denied` node and its descendants are skipped. Nothing in the module can reach a tool
  any other way. If tools are turned off in Settings, a workflow that uses them is refused (`400 tools_disabled`).
- **Output nodes** in *file* mode call `write_file` (so they ask permission like any write); in *artifact* mode they only
  show the content (the UI opens it in the artifact panel as text or HTML).
- **Live log**: per node, status (`pending`, `running`, `ok`, `failed`, `denied`, `skipped`, `cancelled`), streamed text,
  tool calls and results, permission questions and decisions, error and branch taken.
- **Record**: the run id, the inputs, the order, and per node the status, output (capped at 100,000 characters), error,
  branch, file, artifact, a compact log and `elapsed_s` measured with a monotonic clock, plus the total. Only values
  measured on this run are stored. A record whose run was still `running` when the app stopped is shown as `interrupted`.
- **Limits**: 4 runs active at once (`429 too_many_runs`); a workflow cannot be deleted while it runs (`409`).

### Stop

**Stop** (`POST .../runs/{rid}/stop`) cancels the run's asyncio task. The running node becomes `cancelled`, the rest
`skipped` (`stopped`), an open permission question is withdrawn, the record is written with status `cancelled` and no
node is left `running`. A stop is a cancellation of work in this process: a tool that already finished its side effect
(a written file) is not undone.

## Privacy

A **file input** passes the file's **path**, not its contents; read it with the `read_file` tool in a tool step. The result
of a tool step is then the user's file content. SPIKE keeps that marked: a value is *private* when it came from a tool
result built from a private argument, from a tool that returns private content, or from a specialist answer the
orchestrator flagged private. A specialist step whose prompt contains a private passage (the passage appears in the
prompt through `{{...}}`) passes those passages to the orchestrator in `OrchestratorOptions.private_text`, which marks the
user message with `Message.private`. A `GuardedProvider` that is not allowed to receive files then withholds those
passages, as in a chat. The node and its output are flagged private in the run record and the UI.

This is the `private_text` option added to `OrchestratorOptions` for this feature. It does not weaken any guard: a
workflow cannot send file text to a provider that a chat could not.

## Interface

A pure SVG/React canvas with no diagram library: `web/src/workflow.ts` (the model: add, move, connect, delete, the
rules of what can join, the keyboard reducer, the folding of run events), `WorkflowCanvas.tsx` (the drawing) and
`WorkflowBuilder.tsx` (list, toolbar, properties panel, run panel, history).

- Add a node with the **+ Input / Specialist / Tool / Condition / Output** buttons. Drag a node with the mouse, or move it
  with the keys.
- **Accessible without dragging.** Every node and every connection is a button in the tab order with a spoken label
  (type, name, run state, number of problems). On a selected node: arrows move it (Shift: 4 times as far), **C** starts a
  connection from its output (**T** / **F** from a condition's true / false output), arrows or Tab choose the target (the
  chosen node is announced in a live region), **Enter** connects, **Esc** cancels, **Delete** removes. The properties
  panel has a "connect to" list and a "remove" button for each connection, so the whole canvas is also reachable with
  forms alone. Refused connections say why (cycle, a condition already has an input, a file into a condition...). Opening another workflow or starting a new one asks first when there are unsaved changes.
- The properties panel has the fields of the node type; for a tool, one field per argument of its schema.
- **Check** runs the validation; problems are listed above the canvas, each naming its node (a button that selects it),
  and nodes with problems show a count.
- **Run** needs a saved workflow with no pending edits. While it runs the nodes show their state live, permission cards
  and the per-node log appear below, and **Stop** replaces **Run**. The run history lists stored runs; **View** opens one
  as the same view (or re-attaches to one still running).
- Spanish and English strings for everything shown, including each problem code; light and dark themes use the design
  tokens; narrow screens stack the panels and the canvas scrolls inside its frame.

## Decisions that differ from the obvious

- **No `spike/jobs.py` queue.** It has one slot, a fixed set of job kinds and a worker model that would block behind a
  permission question. Runs are plain asyncio tasks with a registry (stop = cancel the task).
- **`AppState.background()` returns the task** it creates (it returned nothing), so a run can be cancelled.
- **Invalid workflows cannot be saved**, not only not run. A draft the server would refuse stays in the editor.
- **No checkpoints or undo for the files a workflow writes.** They are ordinary `write_file` calls with their permission
  prompt; the existing checkpoint mechanism belongs to chat turns and was not extended.
- **File inputs pass paths**, never contents, so the private-content rules above stay simple and auditable.
- A regular expression is checked for nested quantifiers and run on at most 100,000 characters, which refuses the common
  catastrophic patterns; it is a guard, not a proof against every possible pattern.

## Tests

Python (`pytest tests/test_workflows.py tests/test_workflow_run.py tests/test_workflow_api.py`, 51 tests, no network,
scripted provider and fake tools):

- `test_workflows.py` (19): validation of cycles, unknown specialists and tools, tools that need an answer, unresolved
  or non-upstream variables, argument presence/names/types, port compatibility, condition and output settings, names and
  inputs; template filling and escapes; contains/regex/number tests; planner levels and a joining diamond; input
  binding; versions, refusal to save invalid workflows, export/import round trip (including `año` in UTF-8), pruning,
  broken and linked files, run records.
- `test_workflow_run.py` (20): run order and value passing, named variables, timings, argument conversion, condition
  branches, tool permission ask/deny/allow/policy-deny (a denial ends only its branch), the file output going through
  `write_file`'s permission, failed or missing tools, **stop** (also during a permission question), the parallel
  setting, **privacy** (a guarded provider with `share_files` off never receives the private passage; on, or local, it
  does; taint through tools), specialist failure and skipped-variable errors.
- `test_workflow_api.py` (12): catalog, validation and refusal to save, versions inside the project and its export zip,
  export then import into another project, a full run with the SSE stream and the stored record, permission through
  `/api/permissions`, stop, stop during a permission question, input checks, tools off and stale tools, an interrupted
  run, and a file input through an OpenAI-preset provider that may not receive files.

Web (`cd web && npx vitest run`): `workflow.test.ts` (24: adding and deleting nodes and edges, every refusal rule,
cycle prevention, one input per condition, file-to-condition, candidates, the keyboard path and its notices, drawing
geometry, folding run events and stored records) and `workflowBuilder.test.tsx` (8: Spanish/English key parity including
every problem code, the keyboard-only build, validate and save against a fake server, Delete, a run with a permission
question that is stopped, the confirmation before unsaved changes are discarded).

Browser (`node web/e2e/smoke.mjs`, the flow lives in `web/e2e/workflow.mjs`, against `tests/e2e/serve_scripted.py`): builds
input, specialist, condition and output on the canvas, makes connections with the keyboard and with the panel, checks
that a cycle is refused and that an unfinished tool node is reported and can be deleted with the key, saves, runs (with
the file-write permission), verifies the saved file and the node states and measured times, runs again and stops while the
write waits, and opens the saved workflow on a phone-sized screen without horizontal overflow.

## Not measured, not built

- No real model or weights were used anywhere: specialist steps are tested with scripted providers, so the quality of
  chained model answers is not measured. Times in the records are real measurements of whatever ran; none are claimed
  for any model.
- Dragging nodes and connection ports with a pointer is built but not covered by an automated test (jsdom has no layout
  or pointer capture); the keyboard path that does the same is.
- No loops, no parallel branches inside one node, no sub-workflows, no scheduling or triggers: a run starts when the
  user presses Run.
- No automatic layout; nodes sit where they are put (new ones on a grid).
- The history shows stored records, not a diff between runs; there is no restore of an old version in the UI (versions are
  stored and listed by the API at `GET /api/workflows/{id}/versions`).
- The Windows `cp1252` run was exercised as `LC_ALL=C python -X utf8=0` on Linux, not on Windows.
