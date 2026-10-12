# Dark Current data and measurement sheet

Author-review candidate. No release has been authorized. This sheet describes the recorded studies, not a universal benchmark or a live model service.

## What a reader can use

Reproduce recorded stratified clone-null and target-utility audits for the Dark Current replacement candidate. The integrity check is `python3 verify_release.py`, expected `PASS_RELEASE_FILE_HASHES`. It checks saved bytes only. Live requests require a separately configured and validated runner.

## Composition, reference and collection

### benchmark_original

102 previously selected RewardBench 2 rows

Recorded counts: planned_per_configuration=612, terminal_records=1224, configurations=2.

Reference: Upstream benchmark labels, not independent human re-annotation.

Split: Existing frozen original cohort; no new split introduced by this card.

Entry point: `legacy_v5/analysis/release/verify_and_reanalyze_public_v5.py`. See README for arguments and dependency requirements.

### finite_code

96 constructed finite-domain items in eight families

Recorded counts: terminal_records=2880, planned_records=2880, configurations=3.

Reference: Existing independently verified exhaustive oracle over the declared finite domains; no universal program-equivalence claim.

Split: Fixed finite suite; subsequent reuse is not fresh task sampling.

Entry point: `scripts/analyze_v6.py`. See README for arguments and dependency requirements.

### reference_context

32 selected finite-code items reused from the original suite

Recorded counts: terminal_records=1344, planned_records=1536, configurations=3.

Reference: Inherited finite-domain oracle; an ineligible reference is not automatically a known incorrect candidate.

Split: Exploratory reused subset.

State: PARTIAL_HOLD_TRANSPORT_OR_MODEL

Entry point: `scripts/analyze_v7.py`. See README for arguments and dependency requirements.

### configuration_bridge

The same 102 RewardBench 2 rows as benchmark_original

Recorded counts: terminal_records=1224, planned_records=1224, configurations=2.

Reference: Same upstream labels; different recorded served configurations.

Split: Cross-configuration bridge on prior-outcome items, not a fresh-item study.

Entry point: `v8_statistical/analyze_v8_public.py`. See README for arguments and dependency requirements.

### additional_local_output_hold

The same 102 source rows, six conditions per task, one named local Devstral Small 2 configuration.

Recorded counts: planned_records=612, terminal_records=612, valid=401, invalid=211, configurations=1. All output invalidity is retained; the campaign-wide invalid ceiling is 1%.

State: OPERATIONAL_HOLD_BOTH_CRITERIA. No clone/utility estimates or certificates are produced. The two criterion tests form a separate two-member Holm family, preserving the original families.

Reference and split: Same upstream benchmark labels and prior-outcome cohort; no fresh sampling or human semantic-equivalence validation. Raw benchmark text and returned response text are excluded.

Entry point: `local_output_hold/verify_recorded.py`. This reconstructs saved counts and gate state from metadata, rather than running model inference or statistical resampling. Local tag/blob identity is recorded; upstream checkpoint identity and outgoing rights remain unverified.

## Observation and uncertainty units

Two display orders and repeated criteria belong to the same item; terminal calls are not independent task samples. Clone-core certification is nominal and marginal over a finite template set.

Invalid and missing observations: Invalid responses are retained in planned denominators as specified by the frozen analyses; partial configurations remain HOLD.

## Conditions and preprocessing

Served labels and request configuration are recorded; weight digests are not certified. Frozen study manifests and analysis sources define the prompt, extraction and comparison contracts. This documentation update introduces no new split, fit or model call. Returned decoder usage, native execution records and saved-policy decisions are different units.

## Recommended use and limits

Use the saved data to reconstruct the reported study-specific quantities and inspect counterexamples. Reuse owned controls only within their declared oracle domain. Do not infer population-wide model ranking or general semantic correctness.

- No low-null-to-high-utility guarantee
- No latent geometric mechanism or population-wide judge ranking
- No new model or statistical experiment from this documentation update

## Distribution and maintenance

Contains: Saved verdict metadata, finite owned code stimuli, source, figures, analyses and provenance. Original benchmark prompts/responses are excluded.

Excluded: Raw RewardBench prompts/responses, Book-derived raw code, Human-equivalence labels: 51 annotation candidates, zero human labels.

Shared material: The controlled 456-program demonstration and sanitized historical 580-row audit are shared supporting material with Code Evidence, not independent replications.

Outgoing license: NOT_SELECTED. `COMPONENTS.json` and `FILE_RIGHTS_LEDGER.json` preserve per-component notice and review obligations. New data collection, model weights, canonical inputs or expanded references must be versioned and reviewed separately. Do not silently repair an old run or pool repeated conditions as new independent observations. Maintainer contact, rights clearance and final publication scope remain author decisions.

## Extending to another evaluator

[EVALUATION_DATASHEET_TEMPLATE.json](EVALUATION_DATASHEET_TEMPLATE.json) is a proposed documentation template: define the independent unit, truth, model/configuration, modality contract, calibration/evaluation split, planned denominator, invalid handling, uncertainty and resource accounting before a new run. It is not a validated interoperability standard or an implemented universal evaluator adapter.

This artifact-specific sheet follows the documentation purpose of [Datasheets for Datasets](https://arxiv.org/abs/1803.09010). It does not claim to implement every question in that framework. Existing structured fields and source hashes remain in [DATA_CARD.json](DATA_CARD.json).


## Held-source mixture

Unit: 485 selected RewardBench2 rows, with two dependent signal display orders and one exact-clone comparison per criterion. There are 2910 comparison terminals, not 2910 independent tasks.

Selection: prior 102 and known 145 rows and normalized prompt clusters were excluded before result collection; the original pair selector and response-length gates were retained. The six strata have 159/83/41/77/100/25 rows. Normalized uniqueness does not establish semantic independence or absence of training contamination.

Reference and split: upstream source preferences; one fixed surviving mixture, no human re-annotation. Ties25 is a census of the surviving stratum. The balanced nested150 and subset/macro summaries are secondary descriptions.

Configuration and disclosure: one installed raw consumer, two aggregate working passes, zero invalid outputs. Earlier strict102 failures and Devstral612 operational HOLD remain. Installed hashes do not certify upstream identity or the full license chain.

Reproduction: [held_source485/README.md](held_source485/README.md) documents metadata-only checks; raw-response parsing and bootstrap redraws are excluded. [PROTOCOL_AND_LIMITS.md](held_source485/PROTOCOL_AND_LIMITS.md) states the frozen target, denominator, family and limits. Outbound source/output metadata rights, metadata redistribution rights and license selection remain pending.


Current prose-scope revision: prepared named manuscript20pages/4figures/8tables. Clone-error binomial and fixed-mixture task-bootstrap alignment bounds are separate marginal working-model quantities. Holm applies to the two clone p-values only. Earlier primary/new-configuration replay layers support their stated recomputation; prepared612-call/485-row layers support count/hash inspection and saved-value checks only. The latter provide no raw reparse, live generation, bootstrap redraw or p/CI recomputation. Scientific records, analyzers and figure assets are byte unchanged. Source/PDF and current hash bindings are revised; outgoing license and final release decisions remain pending. This candidate is not public or submitted.


Related-work target clarification: JRH stress-tests accuracy under formatting, paraphrase, verbosity and label-flipping perturbations. The current paper attributes the identical-answer calibration check to MT-Bench, notes the reliability-versus-validity distinction in Norman et al., and declares input-stratified clone null and target utility estimands separately. Clone and utility bounds are not a joint population guarantee. Two new manuscript formats were cold-compiled and rendered for this meaning revision; scientific data, analyzers, figures and existing HOLDs remain unchanged. Publication, outgoing-license and final release decisions remain pending.


Current reading guide separates operational eligibility, non-tie exact-duplicate evidence and target-specific utility. The two saved neutral gpt-oss clone events occur at source rows 508 and 628 in Precise IF, with stored valid A, stop finish, IDENTICAL order and chosen-clone roles. Stored hash fields identify their retained records; no raw response content is reparsed or re-hashed here. No position-bias, concentration, common-mechanism or new-science claim is made. Current named paper has 20 pages; anonymous author-review format has 20 pages. Short end-page layout HOLDs remain. Publication, outgoing-license and final release decisions remain pending.

The current preparation-assistance disclosure is concise and generic; experimental model identities and configurations remain separate.

Current edition: the named manuscript uses the TMLR preprint style, 20 pages and 12 objects. Its working-model interpretation and audit-to-selection guidance are clarified; scientific results and figures are unchanged. The current generic preparation-assistance statement is on the first page by author instruction.
