# SATIM Query Playbook

## Top recurrent routes
Group `SATIM_GRAPH_EDGES.csv` by `source` where `edge_type = HAS_VERTEX`.

## Low confidence gaps
Filter `SATIM_TRACK_LEDGER.csv` where `verification_score < 80`.

## Promote candidates
Require identity, timestamp, coordinate, altitude/speed, and visual agreement.
