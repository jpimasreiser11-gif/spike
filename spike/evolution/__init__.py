"""Evolution: SPIKE learns from its own use, on the user's computer, and nothing changes what it does without
passing a local check first. Corrections become rules and test examples (E1), route corrections tune the router
behind its protected test (E2), failures are kept with their cause and fix (E3), and reviewed failures become eval
questions (E4). `checks` runs the regression gate (E5) and `store` keeps every version so any change can be
undone (E6)."""
