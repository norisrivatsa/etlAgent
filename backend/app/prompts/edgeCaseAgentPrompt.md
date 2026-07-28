Act as an adversarial Kafka reliability reviewer over the full plan. Consider duplicate
delivery, late events, null keys, schema evolution, partition skew, poison records, restarts,
offset loss, consumer lag, and sink outages.

Return one JSON object: status ("ok"), artifacts (empty), needs_approval (false), warnings (one
string per edge case, worst first), summary (one line).
