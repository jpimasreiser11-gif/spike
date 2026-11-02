---
name: incident-review
description: Write a blameless incident postmortem using a source-tied timeline and testable prevention actions.
license: Apache-2.0
metadata:
  spike-specialists: code
  spike-keywords: postmortem, incidente, incident
---

# Incident Review

1. Confirm the incident window, timezone, affected service and safe evidence sources. Redact credentials and personal data.
2. Build a timeline of observed events, detection, mitigation and recovery. Label uncertain timestamps and gaps.
3. Separate verified impact from estimates. Trace contributing conditions; do not infer a person's intent.
4. Explain why safeguards did not detect or contain the failure, with evidence and alternative hypotheses.
5. Propose actions with owners, deadlines and observable success criteria. Distinguish mitigation from prevention.
6. End with open questions and the evidence needed to answer them. Never change production during the review.

Respond in the user's language. Distinguish a draft from a verified deliverable.
