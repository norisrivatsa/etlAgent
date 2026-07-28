Analyze the supplied Kafka/Connect/ksqlDB diagnostic evidence. Do not claim a root cause the
evidence doesn't support.

Return one JSON object: status ("ok"), artifacts (empty), needs_approval (false), warnings,
summary (root cause and suggested fix, one line).
