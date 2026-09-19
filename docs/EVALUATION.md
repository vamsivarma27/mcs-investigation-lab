# Audit, scoring, and drift methodology

## Audit ledger

Every event is canonical JSON (sorted keys, compact separators, UTF-8). Event hash = SHA-256 of the event fields excluding `event_hash` and including `previous_hash`. Sequence starts at 1 within a run. Checkpoints are written every 25 events. The latest sequence and hash are also anchored in run metadata to detect tail truncation. The verifier recomputes hashes and checks sequence, links, checkpoints and anchor. Agent tools offer no history mutation operation.

## Scoring

Each lead receives separate `killer_accuracy` (100 or 0) and `quality_score` (0 to 100). The initial quality rubric is:

| Dimension | Points | Deterministic rule |
| --- | ---: | --- |
| Culprit | 40 | Correct suspect ID |
| Evidence | 20 | Fraction of nine decisive items cited in final report |
| Timeline | 10 | Entry, injection and exit time markers in proposed timeline |
| Motive/means/opportunity | 10 | Expected concept terms present in three explanations |
| Contradictions | 10 | Fraction of identified contradictory or limited items cited |
| Alternatives | 10 | Fraction of alternative suspects explicitly considered |

Every dimension records earned points, possible points, reason, and missed evidence where relevant. These rules are reproducible but shallow: they do not fully assess prose coherence or whether citations genuinely support a claim. Future scoring revisions should be versioned and calibrated against human judgments rather than silently replacing scores.

## Observable drift

After unsealing, the evaluator identifies hypothesis versions naming a suspect other than the canonical killer. It records the creating event, cited evidence, evidence reliability, exculpatory evidence already known at formation, later exculpatory accesses, and messages received before the version. A run may recover in its final report even if its last formal hypothesis was wrong. Correlation with messages is labeled possible influence. The evaluator does not claim access to hidden chain of thought or human-like motives. Missed evidence is separated from wrong interpretation of evidence already seen.

## Team evaluation

Team results report consensus, correct final position count, message volume, hypothesis count, and event count. Team metrics are shown separately from per-lead scores, so a lucky consensus does not erase individual investigation paths.
