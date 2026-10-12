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
    if len(configs) != 3: raise ValueError("FIXED_FAMILY_CHANGED")
    if list(configs.values()) != read_json((root/"configs.json").read_bytes()): raise ValueError("CONFIG_DRIFT")
    items = [read_json(line) for line in (root/"items.jsonl").read_text().splitlines()]
    schedule = [read_json(line) for line in (root/"schedule.jsonl").read_text().splitlines()]
    by_item = {i["item_id"]: i for i in items}; by_slot = {s["slot_id"]: s for s in schedule}
    families = sorted({i["family"] for i in items})
    if len(by_item) != len(items): raise ValueError("ITEM_COUNT")
    if len(items) != 32 or len(schedule) != len(by_slot) or len(schedule) != 512: raise ValueError("SCHEDULE_COUNT")
    if len(families) != 8 or any(sum(i["family"] == f for i in items) != 4 for f in families): raise ValueError("STRATUM_COUNT")
    expected_design = {(i["item_id"], a, c, o, z) for i in items for c in ("neutral", "strict")
                       for a in ("equivalence", "signal") for o in ("AB", "BA") for z in ("absent", "present")}
    actual_design = {(s["item_id"], s["arm"], s["criterion"], s["order"], s["context"]) for s in schedule}
    if actual_design != expected_design: raise ValueError("DESIGN_COVERAGE")
    for s in schedule:
        if s["family"] != by_item[s["item_id"]]["family"]: raise ValueError("FAMILY_JOIN")
    expected_sequence = [(c, s["slot_id"]) for c in configs for s in schedule]
    journal_bytes = (run/"journal.jsonl").read_bytes()
    rows = [read_json(line) for line in journal_bytes.splitlines()]
    records = {}; pending = None; fatal_seen = False
    metadata = ("config_id", "slot_id", "item_id", "family", "arm", "criterion", "order", "context", "manifest_sha256", "request_sha256")
    for row in rows:
        key = (row["config_id"], row["slot_id"])
        if fatal_seen: raise ValueError("DISPATCH_AFTER_FATAL_EVENT")
        if key != expected_sequence[len(records)]: raise ValueError("FROZEN_SEQUENCE_OR_DUPLICATE")
        if row["manifest_sha256"] != manifest_hash: raise ValueError("MANIFEST_JOIN")
        if any(row[k] != by_slot[key[1]][k] for k in ("item_id", "family", "arm", "criterion", "order", "context")): raise ValueError("SCHEDULE_JOIN")
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
    if progress["manifest_sha256"] != manifest_hash or progress["completed"] != len(records) or progress["planned"] != 1536: raise ValueError("PROGRESS_JOIN")
    if progress["status"] == "COMPLETE" and (len(records) != 1536 or pending): raise ValueError("FALSE_COMPLETION")
    operational, usage, cells = {}, {}, []
    for cid, cfg in configs.items():
        observed = [r for (c, _), r in records.items() if c == cid]
        invalid = sum(not r["valid"] for r in observed)
        ambiguous = int(pending is not None and pending["config_id"] == cid)
        matched = all(r["served_model"] == cfg["served_model"] for r in observed)
        ok = len(observed) == 512 and not ambiguous and matched and invalid/512 <= .01
        operational[cid] = {"status": "PASS" if ok else "HOLD", "completed": len(observed), "planned":512,
                            "missing":512-len(observed),"invalid":invalid,"ambiguous_intents":ambiguous,"served_model_match":matched}
        totals = {"prompt_tokens":0,"completion_tokens":0,"missing_usage_records":0}
        for r in observed:
            u = r["usage"]
            if not isinstance(u,dict) or any(type(u.get(k)) is not int or u[k]<0 for k in ("prompt_tokens","completion_tokens")):
                totals["missing_usage_records"] += 1
            else:
                for k in ("prompt_tokens","completion_tokens"): totals[k] += u[k]
        totals["latency_median_seconds"] = statistics.median(r["latency_seconds"] for r in observed) if observed else None
        usage[cid] = totals
        for criterion in ("neutral","strict"):
            for arm in ("equivalence","signal"):
                selected = [r for r in observed if r["criterion"]==criterion and r["arm"]==arm]
                lookup = {(r["item_id"],r["order"],r["context"]):r for r in selected}
                cell = {"config_id":cid,"criterion":criterion,"arm":arm,"status":"COMPLETE_DESCRIPTIVE" if ok else "HOLD",
                        "observed_calls":len(selected),"planned_calls":128,"planned_tasks":32,
                        "invalid_by_context":{z:sum(not r["valid"] for r in selected if r["context"]==z) for z in ("absent","present")},
                        "complete_tasks_observed":sum(all((i["item_id"],o,z) in lookup for o in ("AB","BA") for z in ("absent","present")) for i in items),
                        "context_adverse_tasks":None,"context_adverse_rate":None,"success_mean_by_context":None,
                        "paired_present_minus_absent":None,"paired_bootstrap":None,"family_paired_means":None}
                if ok:
                    scores, adverse = {}, 0
                    for item in items:
                        iid = item["item_id"]
                        rr = {(o,z):lookup[(iid,o,z)] for o in ("AB","BA") for z in ("absent","present")}
                        def canonical(r,o):
                            if not r["valid"]:return "invalid"
                            if r["winner"]=="tie":return "tie"
                            return "good" if r["winner"]==("A" if o=="AB" else "B") else ("equivalent" if arm=="equivalence" else "bad")
                        adverse += any(not r["valid"] for r in rr.values()) or any(canonical(rr[(o,"absent")],o)!=canonical(rr[(o,"present")],o) for o in ("AB","BA"))
                        scores[iid] = {z:sum(r["valid"] and (r["winner"]=="tie" if arm=="equivalence" else r["winner"]==("A" if o=="AB" else "B")) for o in ("AB","BA") for r in (rr[(o,z)],))/2 for z in ("absent","present")}
                    differences = {iid:s["present"]-s["absent"] for iid,s in scores.items()}
                    strata = [[differences[i["item_id"]] for i in items if i["family"]==f] for f in families]
                    seed = int(sha((manifest_hash+":"+cid+":"+criterion+":"+arm+":v7-context").encode()),16)
                    boot = bootstrap(strata,seed,replicates)
                    cell.update(context_adverse_tasks=adverse,context_adverse_rate=adverse/32,
                                success_mean_by_context={z:statistics.fmean(s[z] for s in scores.values()) for z in ("absent","present")},
                                paired_present_minus_absent=statistics.fmean(differences.values()),
                                paired_bootstrap={"interval_two_sided_95":boot["interval_two_sided_95"],"seed":boot["seed"],"replicates":replicates,"quantile":"type7"},
                                family_paired_means={f:statistics.fmean(s) for f,s in zip(families,strata)})
                cells.append(cell)
    return {"schema":"dc-v7-analysis-v1","fixture":fixture,
            "scope":"Exploratory third-reference context; descriptive intervals; no geometry, parity, full-triad ranking, or confirmatory H1 claim.",
            "inputhashes":{"manifest_sha256":manifest_hash,"journal_sha256":sha(journal_bytes),"analyzer_sha256":sha(Path(__file__).read_bytes())},
            "campaign_status":progress["status"],"terminal_count":len(records),"operational":operational,"cells":cells,"usage":usage}

def main():
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--run",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True);p.add_argument("--fixture",action="store_true");p.add_argument("--bootstrap-replicates",type=int,default=20000)
    args=p.parse_args();result=evaluate(args.root,args.run,args.bootstrap_replicates,args.fixture)
    with args.out.open("x") as f:json.dump(result,f,indent=2,allow_nan=False);f.write("\n")
    print(json.dumps({"terminal_count":result["terminal_count"],"operational":result["operational"],"fixture":args.fixture}))

if __name__=="__main__":main()
