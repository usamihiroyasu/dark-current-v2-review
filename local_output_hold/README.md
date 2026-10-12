# A completed local campaign held for output validity

The existing 102 RewardBench 2 rows were evaluated once on a separately frozen Devstral Small 2 local quantized configuration. All 612 planned comparisons completed. The strict sole-object JSON contract accepted 401 outputs and rejected 211 responses containing Markdown code fences. No fence removal, retry, or response reclassification was performed.

Both criterion cells remain HOLD because the campaign-wide invalid fraction exceeds the prespecified 1% ceiling. Their clone bounds, utility intervals and joint certificates are absent. In particular, the strict clone's 102 valid ties do not certify a subset of the held campaign.

```sh
python3 local_output_hold/verify_recorded.py
```

Run this from the repository root with Python 3.11 or later. Expected status: `PASS_SAVED_OPERATIONAL_HOLD_METADATA`, 102 tasks, 612 terminals, 401 valid, 211 invalid, and zero scientific certificates. It checks saved metadata, six condition counts, usage, identities and gate state. It makes no model calls, computes no bootstrap and executes no benchmark candidates.

`CONFIGURATION_AND_GATE.json` retains the named local request parameters and content digests. `records.jsonl` exports terminal metadata through a fixed whitelist; `OBSERVED_ANALYSIS.json` is a documented metadata export of the completed owner analysis. `SOURCE_MAPPING.json` links the export to the private frozen campaign and independent actual-record reconciliation by hashes.

Raw responses, original benchmark prompt/candidate strings, private routes, local paths and model weights are excluded. Without the excluded original responses, a reader cannot independently reparse their text or recreate inference. The classification/count check is narrower than inference reproduction. Local blob hashes do not establish upstream checkpoint identity or redistribution-license clearance.

These are additional observations on existing tasks, not 612 new tasks or a new benchmark. The output-contract failure does not identify semantic correctness, a model ranking, or an isolated quantization/backend effect. Preparation of this candidate does not establish publication or author approval.
