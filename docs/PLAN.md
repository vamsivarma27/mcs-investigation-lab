# Implementation plan

1. Establish separate public case and evaluator-only vault assets; validate all references and case consistency.
2. Implement an append-only hash-chained event ledger and persisted run/agent state.
3. Build a typed capability dispatcher with deterministic per-agent and per-run policy.
4. Run three isolated lead contexts, bounded workers, audited messaging, belief revisions, independent conclusions, and deliberation.
5. Finalize, unseal, score, analyze drift, and expose replay and comparison data.
6. Add a research dashboard and tests for security boundaries, persistence, audit integrity, and full offline runs.
7. Connect OpenRouter through one provider adapter; verify with a real key when supplied.

SQLite is chosen for a zero-service local first version. The case vault is a separate file read only by the evaluator after FINALIZED. The investigator runtime has no arbitrary file, database, shell, or network tool. For a hostile host or multi-user deployment, move the vault and evaluator into a separate service identity and add authentication before exposing the server beyond localhost.
