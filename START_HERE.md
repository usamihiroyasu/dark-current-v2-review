# Start here: Dark Current

## The finding

An exact-clone gate can pass while strict target utility fails. In the prespecified fresh 102-row study, four configuration-by-criterion cells have zero observed clone preferences; neutral utility passes the working rules in both configurations, strict utility fails in both. A clone check addresses spurious non-tie preferences on identical candidates; it does not establish useful judging on a target task.

HOLD means that a configuration is unevaluable under its declared output-validity gate. The raw-text client submits an explicitly serialized prompt; a quiet clone result and target utility remain separate questions.

Read [the current 21-page TMLR-style manuscript](paper/main.pdf), especially the fresh benchmark table, 485-row extension table and subset figure. [PAPER_EVIDENCE_MAP.json](PAPER_EVIDENCE_MAP.json) binds the four figures and nine tables to saved source/evidence. Empty and whitespace inputs are separate strata, and each gate is tied to the measured configuration.

## Three questions to ask of your judge

| Audit axis | Question | What passing does not establish |
|---|---|---|
| Output eligibility | Were planned requests complete and outputs valid under the fixed decoder? | Semantic correctness |
| Exact-clone response | Did identical candidates induce a non-tie preference? | Useful target selection or universal impartiality |
| Target utility | Did selection align with the declared task target under its working rule? | Human semantic truth or general model ranking |

The frozen 485-mixture passes both aggregate working rules under one installed raw consumer, yet strict PreciseIF is 58/154. The separate 612-output campaign remains scientifically HOLD after the validity gate fails. Neither result is removed to simplify the story.

## Offline entry

From the repository root, Python 3.11+:

```sh
python3 verify_release.py
python3 held_source485/verify_recorded.py
```

Expected saved-record statuses: PASS_RELEASE_FILE_HASHES and PASS_SAVED_METADATA_CHECKS_ONLY. These make zero model calls. The 485-row saved-record check reconciles saved counts, hashes, bindings and stored values; it does not reparse raw responses or recompute bootstrap draws, p-values or confidence intervals. Other study analyzers and their distinct scopes are listed in [README.md](README.md).

## Reuse with the same distinctions

For a future local audit, specify task target, exact clone construction, decoder/output eligibility, configuration identity, planned calls, thresholds, multiplicity and resource budget before observing outcomes. This checklist is a protocol suggestion; no new runnable cross-model harness or general certificate is supplied by it.

The clone binomial summaries are conditional on their declared Bernoulli working model; a fixed outcome-blind battery does not validate these assumptions. Utility bootstrap intervals concern task composition in the declared empirical strata, rather than deployment-population coverage.

Clone Holm correction covers two clone tests. Utility intervals are criterion-specific and not simultaneous population guarantees. Read [DATASHEET.md](DATASHEET.md) and the rights ledger before redistribution. This is an unpublished author-review candidate; scientific HOLD and publication gates remain distinct.


[Experimental environment and reproduction scope](EXPERIMENT_ENVIRONMENT.md).
