# Case engine, agent, and communication protocol

## Agent declaration

A lead begins from a resolved manifest containing `template_id`, `name`, `mission`, `model`, and
`skills`. The name becomes the visible role, the mission becomes the assigned task, and the model
is recorded with the run. Skills affect the investigation tools visible to that agent. They do not
bypass lifecycle, ownership, evidence, communication, or budget policy.

## Public case

Each evidence item has an ID, title, source kind, text, reliability label, tags, and optionally a suspect. Reliability is `verified`, `partial`, `witness_claim`, or `untrusted_document`. Scene inspection reveals starting evidence. Interviews reveal statements associated with a suspect. Record search returns matched records. Timeline inspection returns tagged timeline items. Forensic requests reveal configured follow-up evidence. `inspect_evidence` requires prior discovery. `lab.validate_case` checks references, eight suspects, answer key consistency, accessibility of all evidence, decisive clue availability, and fixed timeline markers.

## Agent identity and context

Agent records include run ID, parent/lead IDs, role, task, depth, status, model, timestamps, tool use, and private evidence knowledge. The model receives this identity, public case summary, permitted tool schemas, its own evidence text, its inbox, its own findings/hypotheses, and lead peer IDs. It does not receive another agent's private context. A worker begins with no inherited evidence.

## Tools

`inspect_crime_scene`, `inspect_evidence`, `request_forensic_analysis`, `interview_suspect`, `search_case_records`, `inspect_timeline`, `submit_finding`, `submit_hypothesis`, `challenge_hypothesis`, `request_specialist`, `create_investigation_task`, `send_message`, `request_peer_review`, `share_finding`, and `submit_final_accusation` are validated with strict Pydantic schemas. The dispatcher emits `TOOL_REQUEST`, then `TOOL_ALLOWED` and `TOOL_RESULT`, or `TOOL_DENIED`. Evidence discovery, interviews, forensic requests, findings, hypothesis versions, worker creation, messages, and accusations emit specific events.

## Messages and beliefs

Message records include sender, recipient, type, content, evidence IDs, task, and timestamp. Cross-run recipients and unknown citations are denied. Explicit evidence sharing grants the cited items to the recipient; ordinary text is not interpreted as a capability. A hypothesis insertion captures suspect, claim, confidence, support, contradictions, reason and superseded ID. There is no in-place hypothesis edit. The final accusation schema requires suspect, confidence, motive, means, opportunity, proposed timeline, cited support and contradictions, unresolved questions and alternatives.

## Replay and graph

The event API returns sequence-ordered canonical events. The graph API derives `DISCOVERED`, `SENT`, `RECEIVED`, `CITED`, `SUPPORTED`, `CONTRADICTED`, `HELD`, `SUPERSEDED`, `DELEGATED`, and `AUTHORED` edges. These are observable links. A received message before a belief change is labeled possible influence, not proven causation.
