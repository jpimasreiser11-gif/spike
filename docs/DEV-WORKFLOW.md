# Dev: plan, act and skills / planificar, actuar y usar skills

Start a planning session with `spike dev ./project --plan`, or use `/plan` in an existing terminal session.
`/plan <task>` both enters planning and sends that task. The existing read-only tool filter removes file writes,
edits, commands and other action tools; this is enforced by the tool registry, not only a prompt. Reading files
and consulting configured providers still follow the existing data-sharing and payment settings. Planning uses
the selected model and can therefore consume its normal budget. It is not an offline analysis command.

Review the answer, then use `/act` and send the change you want applied. `/act` itself sends nothing and executes
nothing. The normal permission prompts, checkpoints and `/undo` remain. A plan is a proposal, not a test result;
ask Dev to run the project's checks once you decide to implement it.

```text
spike dev ./project --plan
> /plan Inspect the parser and propose a fix with acceptance tests
> /skills
> /skill writing-plans Turn these findings into implementation steps
> /act
> Apply step one and run the relevant tests
> /steps
```

`/skills` lists installed skills and whether settings disable them. `/skill <name> <task>` explicitly chooses a
skill for **that turn only**. An unknown or disabled skill is rejected before a model call or history entry.
This command never enables disabled skills, grants tool access or installs executable dependencies. Use the
existing Settings → Skills ZIP importer or `spike skills --help` for the local marketplace workflow.

Saved user turns record their plan/action mode and explicitly selected skills. Reopening a session restores the
mode of its last saved user turn, but does not repeat it. An old session without this metadata retains normal
action mode. `--plan` explicitly overrides the saved mode; `/act` exits it. A mode change without a subsequent
request is not saved. `/clear` starts a fresh conversation while retaining the current mode.

## En español

`spike dev ./proyecto --plan` y `/plan [tarea]` permiten investigar y preparar un plan con herramientas de lectura.
No ofrecen al modelo herramientas de escritura ni de ejecución de comandos, incluso con `--accept-edits`.
Al terminar de revisar, escribe `/act` y luego pide el cambio concreto: salir del plan no ejecuta automáticamente
ninguna tarea. Los permisos y el deshacer continúan funcionando como antes.

Con `/skills` puedes consultar las skills instaladas; `/skill writing-plans <tarea>` fuerza esa skill solo en esa
petición. No cambia las preferencias globales ni activa skills deshabilitadas. Forge ofrece también selección e
importación de skills mediante su formulario de revisión, usando el mismo motor y los permisos existentes.

## Validation boundary

`tests/test_dev_workflow.py` uses temporary folders and a scripted provider, including an attempted write during
planning and approval/undo after returning to action mode. No model weights, training or paid providers were used.
The quality of plans and coding results remains **not measured with real weights** in this delivery. Dev here is
the terminal agent; it is not yet a graphical session manager for arbitrary local repositories.
