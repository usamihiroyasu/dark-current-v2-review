#!/usr/bin/env python3
"""Controlled synthetic code-gates experiment. No frozen verifier import/mutation."""
import argparse, ast, hashlib, itertools, json, math, operator, subprocess, sys, time
from collections import Counter, deque
from fractions import Fraction
from pathlib import Path

SAFE_BUILTINS = {"sum": sum, "range": range, "len": len, "min": min, "max": max,
                 "int": int, "divmod": divmod}

def expected(row, x):
    s, f = row["specification"], row["family"]
    if f == "count_gt": return len(x) - _bisect_right(sorted(x), s["cutoff"])
    if f == "count_equal": return x.count(s["target"])
    if f == "shifted_sum": return sum(x) + s["offset_k"] * len(x)
    if f == "rotate_left":
        q = deque(x); q.rotate(-s["k"]); return list(q)
    if f == "clamp":
        lo, hi = s["lo"], s["hi"]
        return (lo + hi + abs(x - lo) - abs(x - hi)) // 2
    if f == "parity_sum":
        return functools_reduce_xor((v & 1 for v in x), s["affine_offset_k"] & 1)
    if f == "floor_div": return math.floor(Fraction(x, s["divisor_d"]))
    if f == "interval_contains": return x in set(range(s["lo"], s["hi"] + 1))
    raise AssertionError(f)

def functools_reduce_xor(vals, init):
    for v in vals: init ^= v
    return init

def _bisect_right(a, x):
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] <= x: lo = mid + 1
        else: hi = mid
    return lo

def domain_cases(row):
    d = row["specification"]["input_domain"]
    if d["type"] == "int":
        return list(range(d["range"][0], d["range"][1] + 1))
    lo, hi = d["element_range"]; lr = d["length_range"]
    out = []
    for n in range(lr[0], lr[1] + 1):
        for v in itertools.product(range(lo, hi + 1), repeat=n):
            out.append(list(v))
    return out

def is_safe(code):
    if any(t in code for t in ("__", "import", "open(", "exec(", "eval(")):
        return False
    try: ast.parse(code)
    except SyntaxError: return False
    return True

def run_candidate(code, cases):
    scope = {"__builtins__": dict(SAFE_BUILTINS)}
    exec(code, scope)
    solve = scope["solve"]
    return [solve(x) for x in cases]

def build_program(cases, expected_vals):
    lines = []
    seen = set()
    for i in range(len(cases)):
        if len(seen) >= 3: break
        key = repr(cases[i])
        if key in seen: continue
        seen.add(key)
        lines.append(f"assert solve({cases[i]!r}) == {expected_vals[i]!r}")
    return "\n".join(lines)

def parse_assert_count(src):
    tree = ast.parse(src)
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            test = node.test
            # exclude truthy constant
            if isinstance(test, ast.Constant) and bool(test.value):
                continue
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                inner = test.operand
                if isinstance(inner, ast.Constant) and inner.value is False:
                    continue
            n += 1
    return n

def execute_isolated(program):
    marker = "CONTROLLED_POST_EXECUTION_OK"
    wrapper = "scope={'__builtins__':{'sum':sum,'range':range,'len':len,'min':min,'max':max,'int':int,'divmod':divmod}}\nexec("+repr(program)+",scope)\nprint("+repr(marker)+")"
    start = time.perf_counter()
    result = subprocess.run([sys.executable,"-I","-c",wrapper],capture_output=True,text=True,timeout=2)
    return result.returncode, result.stdout.strip()==marker, time.perf_counter()-start

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--items",type=Path,required=True);ap.add_argument("--out",type=Path,required=True);args=ap.parse_args()
    rows=[json.loads(x) for x in args.items.read_text().splitlines()]
    assert len(rows)==len({r["item_id"] for r in rows})==96
    prepared=[];audits=[];ineligible=[]
    for r in rows:
        cases=domain_cases(r);assert len(cases)==r["oracle_case_count"] and len(cases)>=3
        oracle=[expected(r,x) for x in cases];outputs={}
        for key in ("code_good","code_equivalent","code_bad"):
            assert is_safe(r[key]);outputs[key]=run_candidate(r[key],cases)
        assert outputs["code_good"]==outputs["code_equivalent"]==oracle
        wrong=[k for k,(a,b) in enumerate(zip(outputs["code_bad"],oracle)) if a!=b]
        assert len(wrong)==r["mismatch_bad_count"] and wrong
        audits.append({"item_id":r["item_id"],"domain_cases":len(cases),"candidate_checks":3*len(cases),"bad_mismatches":len(wrong)})
        first=[0,1,2];witness=[wrong[0]]+[k for k in range(len(cases)) if k!=wrong[0]][:2]
        matches=[k for k in range(len(cases)) if outputs["code_bad"][k]==oracle[k]]
        groups=[("good_spec","code_good",first,oracle,True,True),
                ("equivalent_spec","code_equivalent",first,oracle,True,True),
                ("bad_self_consistent","code_bad",first,outputs["code_bad"],False,True),
                ("bad_independent_witness","code_bad",witness,oracle,False,False)]
        if len(matches)>=3:groups.append(("bad_weak_spec_consistent","code_bad",matches[:3],oracle,False,True))
        else:ineligible.append(r["item_id"])
        for name,key,index,labels,semantic,expected_ge in groups:
            test_cases=[cases[k] for k in index];test_labels=[labels[k] for k in index]
            assert len({repr(x) for x in test_cases})==3
            program=r[key]+"\n"+build_program(test_cases,test_labels)+"\n"
            assert parse_assert_count(program)==3
            prepared.append({"item_id":r["item_id"],"family":r["family"],"group":name,"code_key":key,
                             "program":program,"test_cases":test_cases,"test_labels":test_labels,
                             "GS":True,"semantic_finite_validity":semantic,"expected_GE":expected_ge})
    args.out.mkdir(parents=True,exist_ok=False)
    group_counts=Counter();table=Counter();semantic_table=Counter();records=[]
    for record in prepared:
        rc,marker,elapsed=execute_isolated(record["program"]);ge=rc==0 and marker
        assert ge==record.pop("expected_GE"),(record["item_id"],record["group"],rc)
        record.update(GE=ge,returncode=rc,marker=marker,elapsed_seconds=elapsed,
                      program_sha256=hashlib.sha256(record["program"].encode()).hexdigest())
        group_counts[record["group"]]+=1;table[f'GS={int(record["GS"])},GE={int(ge)}']+=1
        semantic_table[f'GE={int(ge)},semantic={int(record["semantic_finite_validity"])}']+=1;records.append(record)
    candidate_path=args.out/"candidates.jsonl";candidate_path.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in records))
    (args.out/"oracle_audit.json").write_text(json.dumps({"audits":audits,"weak_spec_ineligible_items":ineligible},indent=2)+'\n')
    summary={"status":"PASS_CONTROLLED_GATE_PREDICTIONS","items":96,"candidates":len(records),"group_counts":dict(group_counts),
             "GS_GE_table":dict(table),"GE_semantic_table":dict(semantic_table),"weak_spec_ineligible":len(ineligible),
             "independent_domain_vectors":sum(a["domain_cases"] for a in audits),"candidate_oracle_checks":sum(a["candidate_checks"] for a in audits),
             "items_sha256":hashlib.sha256(args.items.read_bytes()).hexdigest(),"candidates_sha256":hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
             "script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "scope":"Planted finite-domain errors and deliberately selected tests; not natural LLM error prevalence or a secure sandbox benchmark.",
             "execution":"Trusted synthetic programs in Python -I subprocess, external completion marker; not the original Docker environment."}
    (args.out/"summary.json").write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))

if __name__=="__main__":main()
