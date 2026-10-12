# Reproduction routes

The [manuscript](paper/main.pdf), [evidence map](PAPER_EVIDENCE_MAP.json), and [configuration map](STUDY_CONFIGURATION_MAP.json) connect the current paper to its study-specific assets. This private author-review repository has not been publicly released.

## Saved records and file integrity

| Route | Command | Scope |
|---|---|---|
| File integrity | `python3 verify_release.py` | Checks the release manifest's file hashes |
| 485-row extension | `python3 held_source485/verify_recorded.py` | Checks saved counts, IDs, criterion/order slots, bindings, and recorded source-preference means |
| Local output-contract audit | `python3 local_output_hold/verify_recorded.py` | Reconciles 612 completed outputs: 401 valid and 211 invalid; both criteria remain HOLD |

The latter two routes inspect exported metadata. Original response text is excluded, so they do not reparse responses, reproduce inference, or redraw confidence bounds. The 485-row route retains 2,910 valid terminals and zero invalid terminals.

## Statistical recomputation from saved verdicts

Use the commands recorded for each study in [PAPER_EVIDENCE_MAP.json](PAPER_EVIDENCE_MAP.json):

- Fresh 102-row benchmark (archive V5): `legacy_v5/analysis/release/verify_and_reanalyze_public_v5.py`.
- Finite-domain code study (V6): `scripts/analyze_v6.py` with its frozen inputs and saved run.
- Context audit with incomplete cells (V7): `scripts/analyze_v7.py`; held cells remain held.
- Additional configurations on the same 102 rows (V8): `v8_statistical/analyze_v8_public.py`.

The map supplies complete arguments and distinct output destinations. The stored parent receipts record the earlier replay checks. Re-evaluating the same rows adds calls, not independent task units. The prepared 485-row and 612-output exports provide metadata checks rather than statistical recomputation or new generation.

Clone tests use their study-specific Bernoulli working model and multiplicity family; utility intervals use fixed-stratum or template-family task resampling. These are marginal audit quantities, without a joint deployment-population guarantee.

## Figures

1. **Workflow.** The retained DOT source matches the included PDF in the earlier 150-dpi pixel and text comparison; PDF bytes differ. See the [build recipe](figure_reproduction/dark/PROTOCOL_FIGURE_BUILD.md) and [verification](FIGURE_BUILD_VERIFICATION.json).
2. **Historical decomposition.** The archived TeX compiles to a different, crowded layout. It does not reproduce the revised PDF, so this route remains HOLD.
3. **Matched clone and utility gates.** The [editable SVG](figure_reproduction/dark/dark_joint_gates.svg), [renderer](figure_reproduction/dark/render_dark.py), and [rounded plotting values](figure_reproduction/dark/dark_figure_data.json) bind to the retained primary table. Plotted one-sided bounds are marginal, not simultaneous bands.
4. **485-row subset alignment.** The [figure inputs and renderer](figure_reproduction/held485/README.md) bind twelve descriptive subset cells to the retained figure. Subset rates have no confidence intervals, tests, or certificates.

Figures and scientific records are unchanged by the prose revision. Rendering a saved figure adds no observation.

## Remaining boundaries

The controlled A0/A1 table and historical parser figure lack a public primary-record/tabulation route. The complete historical live request profile is outside this export. Raw benchmark text, generated candidate bodies, original responses, weights, and private operating information are excluded. A new inference run requires its own upstream sources, serving contract, and frozen protocol; the quick checks do not supply a general cross-model runner.

Source labels and finite-domain truth are separate targets. The 51 human-equivalence items remain unlabelled and excluded. Native weights/context, unseen-task performance, human semantic truth, and deployment-loss reduction are outside the saved-record checks. See the [dataset scope](DATASHEET.md), [configuration map](STUDY_CONFIGURATION_MAP.json), and [rights ledger](FILE_RIGHTS_LEDGER.json) before reuse. Outgoing licensing and public-release approval remain pending.
