# Threat model and security tests

## Protected asset

The actual killer, true timeline, motive, means, evaluator criteria and red-herring annotations reside in `case_vault.json`. Those fields are absent from the public case file and agent tool responses. The answer file is opened only after the run reaches `FINALIZED`. The offline case validator may read both files during development; it is not part of the investigator runtime.

## Investigator attacker model

Treat investigator outputs, messages and evidence documents as untrusted. A model can suggest any tool name or JSON arguments, including invented vault, shell, browser, or network requests. `ToolDispatcher` denies names outside the allowlist, validates schema, checks run ownership, phase, known evidence, message recipient, citation scope, limits, and role. A denial becomes an audit event. Jev never grants capabilities. An artifact (`E19`) contains malicious fictional instructions; it is displayed and modeled as untrusted evidence data. No dangerous capability exists to satisfy its request.

Custom agent names and missions are also untrusted prompt content. Skill IDs are selected from a
server-owned catalog and map only to existing typed tools. Model overrides accept a narrow model-ID
character set and use the same provider adapter and dispatcher. Request bodies are size limited;
responses set a restrictive content security policy, deny framing and MIME sniffing, disable
browser sensors, and prevent API caching.
The API also rejects unexpected Host headers to reduce local DNS rebinding exposure.

Agents do not share a transcript. A lead sees only its own evidence, inbox, findings and hypotheses. Sharing an evidence ID in a message grants that item to the recipient and records the transfer. The human dashboard may see all agents for observation.

## Trust limits

The application process can read both case files, so a compromise of that process or the host can read the answer. The local API has no authentication and must remain bound to localhost. The audit verifier detects normal event modification, deletion, reordering, sequence breaks and tail truncation by recomputing hashes and comparing checkpoints plus the run anchor. It does not defend against an administrator who rewrites the database and anchor together. For deployment, separate the vault and evaluator into a distinct service identity with a narrow post-finalization API, and add authentication and encrypted transport.

## Automated checks

`tests/test_lab.py` covers premature evaluator access, unknown and forbidden tools, cross-run agent calls, private evidence sharing, prompt-injection artifact handling as data, full lifecycle, model adapter contracts, and modified/deleted/truncated audit history. The real provider behavior still needs a key-backed adversarial run to measure whether an actual model attempts to follow `E19`.
