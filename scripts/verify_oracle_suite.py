"""Independent finite-domain verification; never consult generator oracle code."""
import bisect
import collections
import functools
import hashlib
import itertools
import json
import math
import operator
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "v6_frozen/items.jsonl"
rows = [json.loads(s) for s in ITEMS.read_text().splitlines()]
assert len(rows) == len({r["item_id"] for r in rows}) == 96
assert collections.Counter(r["family"] for r in rows) == {f: 12 for f in {
    "count_gt", "shifted_sum", "rotate_left", "count_equal", "clamp",
    "parity_sum", "floor_div", "interval_contains"}}

def expected(row, x):
    s, f = row["specification"], row["family"]
    if f == "count_gt": return len(x) - bisect.bisect_right(sorted(x), s["cutoff"])
    if f == "count_equal": return x.count(s["target"])
    if f == "shifted_sum": return sum(x) + s["offset_k"] * len(x)
    if f == "rotate_left":
        q = collections.deque(x); q.rotate(-s["k"]); return list(q)
    if f == "clamp":
        lo, hi = s["lo"], s["hi"]
        return (lo + hi + abs(x-lo) - abs(x-hi)) // 2
    if f == "parity_sum":
        return functools.reduce(operator.xor, (v & 1 for v in x), s["affine_offset_k"] & 1)
    if f == "floor_div": return math.floor(Fraction(x, s["divisor_d"]))
    if f == "interval_contains": return x in set(range(s["lo"], s["hi"]+1))
    raise AssertionError(f)

audits = []
for row in rows:
    domain = row["specification"]["input_domain"]
    if domain["type"] == "int":
        cases = list(range(domain["range"][0], domain["range"][1]+1))
    else:
        lo, hi = domain["element_range"]
        cases = [list(v) for n in range(domain["length_range"][0], domain["length_range"][1]+1)
                 for v in itertools.product(range(lo, hi+1), repeat=n)]
    bad, checks = 0, 0
    for key in ("code_good", "code_equivalent", "code_bad"):
        code = row[key]
        assert not any(v in code for v in ("__", "import", "open(", "exec(", "eval("))
        scope = {"__builtins__": {"sum": sum, "range": range, "len": len,
                  "min": min, "max": max, "int": int, "divmod": divmod}}
        exec(code, scope)
        mismatches = sum(scope["solve"](x) != expected(row, x) for x in cases)
        if key == "code_bad": bad = mismatches; assert bad > 0
        else: assert mismatches == 0, (row["item_id"], key, mismatches)
        checks += len(cases)
    assert len(cases) == row["oracle_case_count"]
    assert bad == row["mismatch_bad_count"]
    assert row["code_good"] != row["code_equivalent"]
    audits.append({"item_id": row["item_id"], "domain_cases": len(cases),
                   "candidate_checks": checks, "bad_mismatches": bad})
receipt = {"status": "PASS_INDEPENDENT_EXHAUSTIVE_ORACLE", "items": len(rows),
           "domain_cases": sum(a["domain_cases"] for a in audits),
           "candidate_checks": sum(a["candidate_checks"] for a in audits),
           "items_sha256": hashlib.sha256(ITEMS.read_bytes()).hexdigest(),
           "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "scope": "eight fixed templates, declared finite input domains; not human preference"}
(ROOT / "v6_frozen/INDEPENDENT_ORACLE_RECEIPT.json").write_text(json.dumps(receipt, indent=2)+"\n")
print(json.dumps(receipt))
