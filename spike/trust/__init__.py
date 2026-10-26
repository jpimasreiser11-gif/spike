"""Trustworthy answers: what an answer says is split into claims, each labelled by what backs it (`claims`), the
sources it cites are inspected (`citations`, `match`), the evidence of a run is collected from its events
(`evidence`), and a low-confidence answer can be offered to an external provider, only on the user's click
(`escalate`). Everything except the optional model pass is deterministic text matching: no model decides that a
claim is verified."""
