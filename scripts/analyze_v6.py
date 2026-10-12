"""Offline evaluator of the outcome-blind, frozen V6 protocol; no network."""
import argparse
from verify_export import verify_original_files
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

def sha(data):
    return hashlib.sha256(data).hexdigest()

def unique_object(pairs):
    if len(pairs) != len({k for k, _ in pairs}):
        raise ValueError("DUPLICATE_JSON_KEY")
    return dict(pairs)

def read_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))

def verdict(content):
    try:
        obj = read_json(content)
        if isinstance(obj, dict) and set(obj) == {"winner"} and obj["winner"] in ("A", "B", "tie"):
            return obj["winner"]
    except (ValueError, TypeError):
        pass
    return None

def binom_cdf(x, n, p):
    if not 0 <= p <= 1 or not 0 <= n or int(n) != n:
        raise ValueError("INVALID_BINOMIAL_ARGUMENT")
    if x < 0: return 0.0
    if x >= n: return 1.0
    if p == 0: return 1.0
    if p == 1: return 0.0
    return math.fsum(math.comb(n, k) * p**k * (1-p)**(n-k) for k in range(int(x)+1))

def cp_upper(x, n, alpha=0.05):
    if not 0 <= x <= n or n < 1 or not 0 < alpha < 1:
        raise ValueError("INVALID_CP_ARGUMENT")
    if x == n: return 1.0
    if x == 0: return 1-alpha**(1/n)
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo+hi)/2
        if binom_cdf(x, n, mid) > alpha: lo = mid
        else: hi = mid
    return (lo+hi)/2

def holm(pvalues):
    if any(not 0 <= p <= 1 for p in pvalues): raise ValueError("INVALID_PVALUE")
    adjusted = [None]*len(pvalues); previous = 0.0
    for rank, index in enumerate(sorted(range(len(pvalues)), key=lambda i: (pvalues[i], i))):
        previous = min(1.0, max(previous, (len(pvalues)-rank)*pvalues[index]))
        adjusted[index] = previous
    return adjusted

def quantile(values, probability):
    if not values or not 0 <= probability <= 1: raise ValueError("INVALID_QUANTILE")
    values = sorted(values); position = (len(values)-1)*probability
    left = math.floor(position); right = math.ceil(position)
    return values[left] + (position-left)*(values[right]-values[left])

def bootstrap(strata, seed, replicates):
    rng = random.Random(seed); results = []
    for _ in range(replicates):
        results.append(statistics.fmean(statistics.fmean(rng.choice(s) for _ in range(len(s))) for s in strata))
    return {"lower_one_sided_95": quantile(results, 0.05),
            "interval_two_sided_95": [quantile(results, 0.025), quantile(results, 0.975)],
            "replicates": replicates, "seed": str(seed), "quantile": "type7"}

def evaluate(root, run, replicates=20000, fixture=False):
    root, run = Path(root), Path(run)
    manifest_bytes = (root/"manifest.json").read_bytes(); manifest_hash = sha(manifest_bytes)
    manifest = read_json(manifest_bytes)
    verify_original_files(root, manifest)
    if not fixture and replicates != 20000: raise ValueError("FROZEN_BOOTSTRAP_COUNT")
    configs = {c["id"]: c for c in manifest["configs"]}
    if len(configs) != 3 or manifest["dc_family_size"] != 6: raise ValueError("FIXED_FAMILY_CHANGED")
    if list(configs.values()) != read_json((root/"configs.json").read_bytes()): raise ValueError("CONFIG_DRIFT")
    items = [read_json(line) for line in (root/"items.jsonl").read_text().splitlines()]
    schedule = [read_json(line) for line in (root/"schedule.jsonl").read_text().splitlines()]
    by_item = {i["item_id"]: i for i in items}; by_slot = {s["slot_id"]: s for s in schedule}
    families = sorted({i["family"] for i in items})
    if len(by_item) != len(items): raise ValueError("ITEM_COUNT")
    if len(items) != 96 or len(schedule) != len(by_slot) or len(schedule) != 960: raise ValueError("SCHEDULE_COUNT")
    if len(families) != 8 or any(sum(i["family"] == f for i in items) != 12 for f in families): raise ValueError("STRATUM_COUNT")
    expected_design = {(i["item_id"], a, c, o) for i in items for c in ("neutral", "strict")
                       for a in ("clone", "equivalence", "signal") for o in (("AB",) if a == "clone" else ("AB", "BA"))}
    actual_design = {(s["item_id"], s["arm"], s["criterion"], s["order"]) for s in schedule}
    if actual_design != expected_design: raise ValueError("DESIGN_COVERAGE")
    for s in schedule:
        if s["family"] != by_item[s["item_id"]]["family"]: raise ValueError("FAMILY_JOIN")
    expected_sequence = [(c, s["slot_id"]) for c in configs for s in schedule]
    journal_bytes = (run/"journal.jsonl").read_bytes()
    rows = [read_json(line) for line in journal_bytes.splitlines()]
    records = {}; pending = None; fatal_seen = False
    metadata = ("config_id", "slot_id", "item_id", "family", "arm", "criterion", "order", "manifest_sha256", "request_sha256")
    for row in rows:
        key = (row["config_id"], row["slot_id"])
        if fatal_seen: raise ValueError("DISPATCH_AFTER_FATAL_EVENT")
        if key != expected_sequence[len(records)]: raise ValueError("FROZEN_SEQUENCE_OR_DUPLICATE")
        if row["manifest_sha256"] != manifest_hash: raise ValueError("MANIFEST_JOIN")
        if any(row[k] != by_slot[key[1]][k] for k in ("item_id", "family", "arm", "criterion", "order")): raise ValueError("SCHEDULE_JOIN")
        if len(row["request_sha256"]) != 64: raise ValueError("REQUEST_HASH")
        if row["type"] == "intent":
            if pending is not None: raise ValueError("INTENT_WITHOUT_TERMINAL")
            pending = row
        elif row["type"] == "terminal":
            if pending is None or any(pending[k] != row[k] for k in metadata): raise ValueError("TERMINAL_WITHOUT_MATCHED_INTENT")
            parsed = verdict(row["content"])
            expected_model = configs[key[0]]["served_model"]
            valid = parsed is not None and row["finish_reason"] == "stop" and row["served_model"] == expected_model and not row["error_class"]
            if row["valid"] is not valid or row["winner"] != (parsed if valid else None): raise ValueError("STORED_VERDICT_MISMATCH")
            if not isinstance(row["latency_seconds"], (int, float)) or not math.isfinite(row["latency_seconds"]) or row["latency_seconds"] < 0: raise ValueError("LATENCY_SCHEMA")
            records[key] = row; pending = None
            fatal_seen = bool(row["error_class"]) or row["served_model"] != expected_model
        else: raise ValueError("EVENT_TYPE")
    progress = read_json((run/"progress.json").read_bytes())
    if progress["manifest_sha256"] != manifest_hash or progress["completed"] != len(records) or progress["planned"] != 2880: raise ValueError("PROGRESS_JOIN")
    if progress["status"] == "COMPLETE" and (len(records) != 2880 or pending): raise ValueError("FALSE_COMPLETION")
    operational = {}; usage = {}; cells = []; utility = []; efp = []; joint = []
    for cid, cfg in configs.items():
        observed = [r for (c, _), r in records.items() if c == cid]
        invalid = sum(not r["valid"] for r in observed)
        ambiguous = int(pending is not None and pending["config_id"] == cid)
        model_match = all(r["served_model"] == cfg["served_model"] for r in observed)
        ok = len(observed) == 960 and not ambiguous and model_match and invalid/960 <= 0.01
        operational[cid] = {"status": "PASS" if ok else "HOLD", "completed": len(observed), "planned": 960,
                            "missing": 960-len(observed), "ambiguous_intents": ambiguous, "invalid": invalid,
                            "invalid_rate_observed": invalid/len(observed) if observed else None, "served_model_match": model_match}
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "missing_usage_records": 0}
        for r in observed:
            u = r["usage"]
            if not isinstance(u, dict) or any(type(u.get(k)) is not int or u[k] < 0 for k in ("prompt_tokens", "completion_tokens")):
                totals["missing_usage_records"] += 1
            else:
                for k in ("prompt_tokens", "completion_tokens"): totals[k] += u[k]
        totals["latency_median_seconds"] = statistics.median(r["latency_seconds"] for r in observed) if observed else None
        usage[cid] = totals
        for criterion in ("neutral", "strict"):
            selected = [r for r in observed if r["criterion"] == criterion]
            clones = [r for r in selected if r["arm"] == "clone"]
            adverse = sum(not r["valid"] or r["winner"] != "tie" for r in clones)
            cells.append({"config_id": cid, "criterion": criterion, "observed": len(clones), "planned": 96,
                          "adverse": adverse, "invalid": sum(not r["valid"] for r in clones),
                          "rate": adverse/len(clones) if clones else None,
                          "upper_one_sided_95": cp_upper(adverse, len(clones)) if clones else None,
                          "p_raw": binom_cdf(adverse, 96, 0.05) if ok and len(clones) == 96 else 1.0})
            lookup = {(r["item_id"], r["arm"], r["order"]): r for r in selected}
            scores = {}; efp_tasks = {}; classes = Counter()
            order_counts = Counter(); order_success = Counter(); signal_invalid = 0
            for i in items:
                iid = i["item_id"]
                signal = [lookup.get((iid, "signal", o)) for o in ("AB", "BA")]
                for o, r in zip(("AB", "BA"), signal):
                    if r:
                        order_counts[o] += 1; signal_invalid += not r["valid"]
                        order_success[o] += r["valid"] and r["winner"] == ("A" if o == "AB" else "B")
                if all(signal):
                    scores[iid] = sum(r["valid"] and r["winner"] == ("A" if o == "AB" else "B") for o, r in zip(("AB", "BA"), signal))/2
                eq = [lookup.get((iid, "equivalence", o)) for o in ("AB", "BA")]
                if not all(eq): continue
                efp_tasks[iid] = int(any(not r["valid"] or r["winner"] != "tie" for r in eq))
                if any(not r["valid"] for r in eq): classification = "invalid"
                elif all(r["winner"] == "tie" for r in eq): classification = "tie"
                elif any(r["winner"] == "tie" for r in eq): classification = "one_sided_commit"
                else:
                    canonical = ["good" if r["winner"] == ("A" if o == "AB" else "B") else "equivalent" for o, r in zip(("AB", "BA"), eq)]
                    classification = "stable_content_preference" if canonical[0] == canonical[1] else "position_conflict"
                classes[classification] += 1
            urow = {"config_id": cid, "criterion": criterion, "complete_tasks_observed": len(scores), "planned_tasks": 96,
                    "mean_complete_tasks_observed": statistics.fmean(scores.values()) if scores else None,
                    "success_by_order": dict(order_success), "observed_by_order": dict(order_counts), "invalid_calls": signal_invalid,
                    "family_means": {f: statistics.fmean(v) if (v := [scores[i["item_id"]] for i in items if i["family"] == f and i["item_id"] in scores]) else None for f in families},
                    "bootstrap": None, "gate_pass": False}
            if ok and len(scores) == 96:
                strata = [[scores[i["item_id"]] for i in items if i["family"] == f] for f in families]
                seed = int(sha((manifest_hash+":"+cid+":"+criterion+":v6-utility").encode()), 16)
                urow["bootstrap"] = bootstrap(strata, seed, replicates)
                urow["gate_pass"] = urow["bootstrap"]["lower_one_sided_95"] >= 0.75
            utility.append(urow)
            eadverse = sum(efp_tasks.values()); en = len(efp_tasks)
            efp.append({"config_id": cid, "criterion": criterion, "complete_tasks_observed": en, "planned_tasks": 96,
                        "adverse_tasks": eadverse, "rate_complete_tasks_observed": eadverse/en if en else None,
                        "upper_one_sided_95": cp_upper(eadverse, en) if en else None,
                        "classes": {k: classes[k] for k in ("invalid", "tie", "stable_content_preference", "position_conflict", "one_sided_commit")},
                        "family_rates": {f: statistics.fmean(v) if (v := [efp_tasks[i["item_id"]] for i in items if i["family"] == f and i["item_id"] in efp_tasks]) else None for f in families},
                        "inferential_status": "DESCRIPTIVE_ONLY"})
    adjusted = holm([c["p_raw"] for c in cells])
    for cell, adj, urow in zip(cells, adjusted, utility):
        cell["p_holm"] = adj
        cell["gate_pass"] = operational[cell["config_id"]]["status"] == "PASS" and adj <= 0.05
        status = ("HOLD" if operational[cell["config_id"]]["status"] != "PASS" else
                  "FAIL_DC" if not cell["gate_pass"] else
                  "PASS_USEFUL_LOW_DC" if urow["gate_pass"] else "PASS_STATISTICAL_BUT_NOT_USEFUL")
        joint.append({"config_id": cell["config_id"], "criterion": cell["criterion"], "status": status})
    paired = {cid: {"strict_minus_neutral_mean": utility[2*k+1]["mean_complete_tasks_observed"]-utility[2*k]["mean_complete_tasks_observed"]
                    if utility[2*k]["complete_tasks_observed"] == utility[2*k+1]["complete_tasks_observed"] == 96 else None}
              for k, cid in enumerate(configs)}
    return {"schema": "dc-v6-analysis-v1", "fixture": fixture, "scope": "Finite declared code domains; fixed eight templates; no human-preference inference, no V5 pooling, no IID population guarantee.",
            "inputhashes": {"manifest_sha256": manifest_hash, "journal_sha256": sha(journal_bytes), "analyzer_sha256": sha(Path(__file__).read_bytes())},
            "campaign_status": progress["status"], "terminal_count": len(records), "operational": operational,
            "dc_family_size": 6, "dc_family": cells, "utility": utility, "efp": efp, "joint": joint,
            "paired_criterion": paired, "usage": usage}

def main():
    p = argparse.ArgumentParser(); p.add_argument("--root", type=Path, required=True)
    p.add_argument("--run", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--bootstrap-replicates", type=int, default=20000); p.add_argument("--fixture", action="store_true")
    args = p.parse_args()
    result = evaluate(args.root, args.run, args.bootstrap_replicates, args.fixture)
    with args.out.open("x") as f: json.dump(result, f, indent=2, allow_nan=False); f.write("\n")
    print(json.dumps({"terminal_count": result["terminal_count"], "joint": result["joint"], "fixture": args.fixture}))

if __name__ == "__main__": main()
