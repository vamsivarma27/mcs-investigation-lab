# Architecture and development guide

## Custom agent layer

`lab/agents.py` is the public extension boundary for agent manifests. The API accepts two or three
validated manifests per run. Each manifest resolves a built-in template plus optional name,
mission, model, and skill overrides. Skill IDs expand to a fixed set of typed tools; arbitrary
manifest text never becomes executable code or a new capability.

Resolved manifests are stored in the immutable run configuration and copied into each agent's
private state. The orchestrator intersects skill permissions with lifecycle permissions before
giving a provider any tool schema. `ToolDispatcher` repeats the authoritative checks when the
model requests a tool.

## Boundaries

The public case engine loads only `lab/data/case_public.json`. The hidden answer lives in `lab/data/case_vault.json`. Only `Evaluator.evaluate` opens the vault, and it checks the persisted run phase before doing so. The orchestrator's model context builder reads agent state, discovered public evidence, received messages, own findings and hypotheses, and public suspect details. It never imports the vault. Tool dispatch is an explicit allowlist of Pydantic-validated actions. There is no generic SQL, Python, file, HTTP, browser, or external MCP tool available to investigators.

The orchestrator controls lifecycle and budgets. The ledger persists events and projections in SQLite. The API exposes human observation and run creation; it does not expose an endpoint through which an agent can call arbitrary tools. Host the server only on localhost until authentication and process isolation exist.

## Lifecycle

`CREATED → INITIALIZING → INVESTIGATING → INDEPENDENT_CONCLUSIONS → DELIBERATION → FINALIZED → GROUND_TRUTH_UNSEALED → EVALUATING → COMPLETED`. A run may transition to `FAILED` when engineering failures occur. The finalization transition precedes the evaluator call. Final accusations can only be submitted in the independent or deliberation phase by lead agents.

Within a run, lead contexts are separate. The orchestrator gives each lead a bounded turn, then allows created workers to act on later rounds. This is interleaved execution, not parallel model requests. Workers start with empty evidence knowledge and must explicitly report back through messages. New agents cannot recursively delegate beyond configured depth. Each run has its own agent, message, hypothesis, finding, accusation, event, and evaluation records.

## Reproducibility

A run stores the case SHA-256 hash, configured provider/model IDs, Jev setting, tool/prompt/scoring versions, limits, app version, and Git commit when available. Each model response stores the actual returned model ID, usage, latency, cost when returned, action and stated explanation. All permitted context is included in a `MODEL_REQUEST` audit event. The dashboard can compare runs and replay the trace.

## Storage

SQLite is intentionally local and service-free. `runs` and `agents` hold current state, while `events` is the ordered append-only application ledger. Hypotheses are inserted as revisions, not updated. Messages and accusations are append-like records. Process crashes between event append and a projection update may require a future repair/rebuild utility; this prototype avoids making claims of crash-atomic multi-table event sourcing.

## Development

- Case data: `lab/data/`; run the offline validator after edits.
- Typed tools and policy: `lab/tools.py`; add a Pydantic input and enforce knowledge, phase, and run checks.
- Provider integrations: `lab/provider.py`; keep gateway-specific code here.
- Run logic: `lab/orchestrator.py`.
- Evaluation and drift: `lab/evaluator.py`.
- Human API/UI: `lab/api.py` and `lab/static/`.

Run lint, tests, JS syntax check, case validator, and an API mock run before committing. Never commit `.env` or local SQLite files.
