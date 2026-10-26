"""Desktop actions (A19): a task on the user's own screen, done by an API provider with a computer-use tool.

Off by default. SPIKE's local models never touch the desktop: only a configured remote provider whose API has a
computer-use tool does, and every action it asks for waits for the user's approval. `driver` is the small local
layer that takes screenshots and moves the mouse and keyboard with programs the OS already has; `adapters` maps one
provider's computer-use request and response shapes; `session` runs the loop with its approvals, caps and record."""
