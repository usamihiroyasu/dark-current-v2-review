# Start here: Dark Current

## The finding

Passing an exact-clone gate does not establish useful target selection. In the fresh 102-row benchmark study, all four configuration–criterion cells have zero observed clone preferences. Neutral utility passes in both configurations; the strict utility lower bounds do not reach the .75 working threshold. On additional configurations, neutral gpt-oss passes utility while its two clone preferences leave the declared low-null rate uncertified.

The fixed mixture of 485 additional RewardBench 2 rows passes both aggregate working rules for one raw-text configuration, yet strict Precise Instruction Following alignment is 58/154. A separate campaign completes all 612 outputs, with 401 valid and 211 invalid under its frozen parser. It remains HOLD: output validity prevents interpreting its clone and utility cells.

Read [the 21-page manuscript](paper/main.pdf), particularly the fresh benchmark table and the 485-row extension table and subset figure. The [evidence map](PAPER_EVIDENCE_MAP.json) links all four figures and nine tables to their source and saved evidence.

## Three questions to ask of a judge

| Audit axis | Question | Evidence provided |
|---|---|---|
| Output eligibility | Are scheduled requests complete and outputs valid under the declared decoder? | Completeness and output-contract compliance |
| Exact-clone response | Do identical answers induce a non-tie preference? | Null behavior in the declared input stratum |
| Target utility | Does selection align with the declared task target? | Target-selection performance under the study's working rule |

Fix the configuration, consumer contract, target, application loss, thresholds, multiplicity, and resource budget before observing results. Examine the intended task subset alongside the aggregate. Empty and whitespace inputs form separate null strata.

## Choose a reproduction route

For file integrity and the 485-row saved-record check, run from the repository root with Python 3.11+:

```sh
python3 verify_release.py
python3 held_source485/verify_recorded.py
```

Expected statuses are `PASS_RELEASE_FILE_HASHES` and `PASS_SAVED_METADATA_CHECKS_ONLY`. These checks make zero model calls. The [reproduction map](REPRODUCTION_MAP.md) distinguishes these checks from study-specific statistical recomputation, figure rendering, and new inference.

## Interpretation and reuse

Source-label utility and finite-domain code truth have different meanings. Clone binomial summaries use the declared Bernoulli working model; utility bootstrap intervals concern task composition within the fixed empirical strata or templates. Clone Holm families are study-specific: the 485-row extension adjusts its two clone tests. The bounds are marginal, subset rates are descriptive, and non-certification alone does not prove a defect. Deployment benefit requires application-specific evidence.

The [dataset scope](DATASHEET.md), [experimental environment](EXPERIMENT_ENVIRONMENT.md), and [rights ledger](FILE_RIGHTS_LEDGER.json) state the retained assets and reuse conditions. The submitted preprint and its saved evidence are provided here. See [license scope](LICENSE_SCOPE.md) for author-owned assets and retained third-party terms.
