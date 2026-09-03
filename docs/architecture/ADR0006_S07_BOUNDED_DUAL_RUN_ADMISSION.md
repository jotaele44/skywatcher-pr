# ADR 0006 S07 — bounded dual-run admission and operator handoff

## Decision

S07 is the offline, two-phase boundary between Skywatcher S06 trial staging and
later TheHub H08 dual-run readiness evaluation. It never executes a lane and never
invokes H08.

Phase A reads one complete S06 trial package through stable file descriptors,
validates every staged byte, reconstructs campaign, policy, legacy-export,
S05-package and lane bindings, and normalizes injected H09 receipt-verification
results into an immutable content-addressed trial-admission receipt. The same
single-read observation is retained as the only source for later handoff bytes.

Phase B requires the exact campaign trial set, the exact pinned H08 policy and
rollback contracts, globally distinct execution and verification receipts, and a
signed operator authorization whose only allowed action is
`RELEASE_TO_H08_OFFLINE_EVALUATION`. It publishes a deterministic H08 handoff
directory through temporary-sibling staging and one atomic rename.

## Responsibility boundary

- S06 owns deterministic per-trial evidence staging and local object/reference
  coherence.
- H09 owns trusted-key resolution and execution-receipt signature verification.
  S07 receives verification through an injected resolver and loads no keys or
  credentials.
- S07 owns package admission, policy and rollback cross-binding, campaign-wide
  receipt uniqueness, operator release and deterministic transfer.
- H08 owns later schema validation, pair comparison, rollback-readiness analysis
  and immutable comparison/readiness receipts.
- The operator may approve, reject or abort release to offline H08 evaluation.
  That decision is not permission to execute a provider, model, legacy lane,
  candidate lane, certification, active promotion or retirement.

## Trial admission

`compute_s06_trial_admission()` is pure with respect to supplied evidence. It:

1. rejects non-directories and symlinks;
2. requires the exact S06 package file set and a sorted `SHA256SUMS` inventory;
3. reads each source once through a stable descriptor, recomputes its digest and
   requires canonical JSON bytes;
4. validates the expected campaign identity, source set, pins and trial;
5. validates equivalence-policy identity and campaign pin binding;
6. reconstructs legacy-export, legacy-lane, S05-package and candidate-lane
   identities and projections;
7. requires complete accounting, zero schema violations and zero missing
   provenance;
8. binds each full receipt to its compact lane reference and injected H09 result;
9. rejects legacy/candidate run-ID or receipt-digest reuse; and
10. returns `s07_trial_admission_receipt.v1` with all runtime, certification,
    promotion and retirement flags fixed false.

`compute_s06_trial_admission_snapshot()` additionally returns the sealed observed
package used by Phase B. Source paths are fingerprinted and must remain unchanged
through publication; handoff construction never rereads lane content from those
paths.

`record_trial_admission_receipt()` writes a caller-supplied new registry path once.
Exact replay is idempotent and changed replay fails closed.

## Operator authorization

`s07_operator_handoff_authorization.v1` is content-addressed and signature-bound.
The exact schema is validated before decision handling. The only accepted action
is:

```text
RELEASE_TO_H08_OFFLINE_EVALUATION
```

The authorization binds the exact campaign and a handoff-request SHA-256 derived
from campaign, validated policy, admitted trial packages and validated rollback
evidence. It must be approved, unexpired and already signature verified. Reject
and abort decisions produce no handoff package.

## Campaign handoff

`build_h08_operator_handoff()` requires:

- exactly one admitted receipt and one unchanged source package for every campaign
  trial, with at least two trials;
- no additional trials;
- an exact pinned-H08 equivalence policy whose ID and SHA-256 match campaign pins
  and every trial admission;
- exact pinned-H08 rollback evidence with canonical content identity, campaign
  binding, no unexpected writes and complete checks;
- globally unique run IDs, execution-receipt SHA-256 values, H09 verification IDs
  and H09 verification SHA-256 values across all lane and rollback receipts;
- a full rollback receipt bound to an injected H09 verification result; and
- exact-schema, exact-scope operator approval.

The published directory contains campaign, policy, rollback evidence, operator
authorization, trial admissions, H08 lane records, normalized verification
records, `H08_HANDOFF.json` and sorted `SHA256SUMS`. Identical inputs produce
byte-identical packages. Existing identical output is an idempotent replay;
changed output under the same destination fails closed.

## Preserved boundary

S07 adds no network client, provider/model SDK, credential or key loader, database
client, subprocess or container launcher, producer RPC, H08 evaluator,
certification route, active-snapshot promotion, source-package mutation, existing
ledger mutation, operational deletion or retirement authorization.
