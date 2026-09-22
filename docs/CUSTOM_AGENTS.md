# Custom agents and skills

MCS treats an agent as a validated run manifest, not executable user code. A manifest selects a
built-in template and may override its display name, mission, model, and skill list. This keeps
customization reproducible while preserving the investigation sandbox.

## Agent manifest

```json
{
  "template_id": "forensic-analyst",
  "name": "Trace",
  "mission": "Establish means and identity through physical evidence.",
  "model": "google/gemini-3-flash-preview",
  "skills": ["scene-analysis", "forensics", "timeline-analysis", "teamwork"]
}
```

Submit two or three manifests in `POST /api/runs`:

```bash
curl -X POST http://127.0.0.1:8765/api/runs \
  -H 'content-type: application/json' \
  -d '{
    "case_id": "aurora-observatory-1",
    "agents": [
      {"template_id":"forensic-analyst","name":"Trace","mission":"Analyze physical evidence and explain the causal chain.","skills":["scene-analysis","forensics","teamwork"]},
      {"template_id":"skeptical-reviewer","name":"Doubt","mission":"Challenge the leading theory with contradictory evidence.","skills":["records-research","timeline-analysis","teamwork"]}
    ]
  }'
```

Discover the current manifest vocabulary through `GET /api/agent-catalog` or configure the same
fields in **Agent Studio**.

## Skill security model

Each skill expands to a fixed list of typed investigation tools. The server intersects that list
with lifecycle rules before exposing tools to a model. Core finding, hypothesis, and accusation
tools and basic `send_message` remain available to every lead. Deliberation communication remains
available so every team can complete the required protocol. Teamwork adds richer review, sharing,
challenge, and handoff actions during the investigation stage.

Custom names, missions, and evidence are prompt content. They never create capabilities. The
dispatcher independently validates tool name, arguments, run ownership, phase, role, evidence
knowledge, recipient, duplicate reads, and budgets.

## Adding a skill or template

Edit `lab/agents.py`, compose a skill only from existing controlled tools, and add tests that show
both the intended permission and at least one denied permission. A new capability requires a
strict Pydantic schema, policy checks in `ToolDispatcher`, audit events, threat-model documentation,
and adversarial tests.

Provider plugins and remote agent protocols are intentionally outside the current trust boundary.
A future adapter should translate an external agent declaration into this manifest rather than
executing third-party code inside the server process.
