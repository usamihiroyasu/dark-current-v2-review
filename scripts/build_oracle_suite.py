import argparse
import hashlib
import json
import math
import os
import random
from collections import Counter
from itertools import product


def _exec_candidate(code: str):
    restricted_globals = {
        "__builtins__": {
            "range": range,
            "abs": abs,
            "int": int,
            "len": len,
            "sum": sum,
            "min": min,
            "max": max,
            "enumerate": enumerate,
            "zip": zip,
            "list": list,
            "tuple": tuple,
            "bool": bool,
            "map": map,
            "filter": filter,
            "reversed": reversed,
            "sorted": sorted,
            "divmod": divmod,
        }
    }
    exec(code, restricted_globals)
    return restricted_globals["solve"]


def _check_candidate(code: str):
    if "__" in code or "import" in code or "exec" in code or "eval" in code or "open" in code:
        raise ValueError("Candidate code contains forbidden strings")
    try:
        compile(code, "<string>", "exec")
    except SyntaxError as e:
        raise ValueError(f"Candidate syntax error: {e}")


def _make_item(item_id, family, param_index, spec, good_code, equiv_code, bad_code):
    return {
        "item_id": item_id,
        "family": family,
        "parameter_index": param_index,
        "specification": spec,
        "code_good": good_code.strip(),
        "code_equivalent": equiv_code.strip(),
        "code_bad": bad_code.strip(),
    }


def _gen_count_gt(rng):
    cutoffs = rng.sample(range(-24, 25), 12)
    items = []
    for i, c in enumerate(cutoffs):
        spec = {
            "task": "count elements strictly greater than cutoff",
            "input_domain": {
                "type": "list[int]",
                "length_range": [0, 4],
                "element_range": [c - 2, c + 2]
            },
            "cutoff": c,
        }
        good = f"def solve(xs):\n    return sum(1 for x in xs if x > {c})"
        equiv = f"def solve(xs):\n    n=0\n    for x in xs:\n        if x > {c}:\n            n+=1\n    return n"
        bad = f"def solve(xs):\n    return sum(1 for x in xs if x >= {c})"
        items.append(_make_item(f"count_gt_{i}", "count_gt", i, spec, good, equiv, bad))
    return items


def _gen_shifted_sum(rng):
    ks = list(range(1, 13))
    rng.shuffle(ks)
    items = []
    for i, k in enumerate(ks):
        spec = {
            "task": "sum elements shifted by nonzero offset",
            "input_domain": {
                "type": "list[int]",
                "length_range": [0, 4],
                "element_range": [-2, 2]
            },
            "offset_k": k,
        }
        good = f"def solve(xs):\n    return sum(x + {k} for x in xs)"
        equiv = f"def solve(xs):\n    s=0\n    for x in xs:\n        s += x + {k}\n    return s"
        bad = f"def solve(xs):\n    return sum(x - {k} for x in xs)"
        items.append(_make_item(f"shifted_sum_{i}", "shifted_sum", i, spec, good, equiv, bad))
    return items


def _gen_rotate_left(rng):
    ks = list(range(1, 13))
    rng.shuffle(ks)
    items = []
    for i, k in enumerate(ks):
        spec = {
            "task": "rotate list left by k",
            "input_domain": {
                "type": "list[int]",
                "length_range": [0, 6],
                "element_range": [-1, 1]
            },
            "k": k,
        }
        good = f"def solve(xs):\n    if not xs: return []\n    n=len(xs)\n    k={k}%n\n    return xs[k:]+xs[:k]"
        equiv = f"def solve(xs):\n    if not xs: return []\n    n=len(xs)\n    k={k}%n\n    res=[]\n    for i in range(n):\n        res.append(xs[(i+k)%n])\n    return res"
        bad = f"def solve(xs):\n    if not xs: return []\n    n=len(xs)\n    k={k}%n\n    return xs[-k:]+xs[:-k] if k else xs[:]"
        items.append(_make_item(f"rotate_left_{i}", "rotate_left", i, spec, good, equiv, bad))
    return items


def _gen_count_equal(rng):
    targets = rng.sample(range(-24, 25), 12)
    items = []
    for i, t in enumerate(targets):
        spec = {
            "task": "count elements equal to target",
            "input_domain": {
                "type": "list[int]",
                "length_range": [0, 4],
                "element_range": [t - 2, t + 2]
            },
            "target": t,
        }
        good = f"def solve(xs):\n    return sum(1 for x in xs if x == {t})"
        equiv = f"def solve(xs):\n    n=0\n    for x in xs:\n        if x == {t}:\n            n+=1\n    return n"
        bad = f"def solve(xs):\n    return sum(1 for x in xs if x == {t + 1})"
        items.append(_make_item(f"count_equal_{i}", "count_equal", i, spec, good, equiv, bad))
    return items


def _gen_clamp(rng):
    items = []
    used_pairs = set()
    for i in range(12):
        while True:
            lo = rng.randint(-10, 10)
            hi = rng.randint(-10, 10)
            if lo < hi and (lo, hi) not in used_pairs:
                used_pairs.add((lo, hi))
                break
        spec = {
            "task": "clamp scalar to [lo,hi]",
            "input_domain": {
                "type": "int",
                "range": [-15, 15]
            },
            "lo": lo,
            "hi": hi,
        }
        good = f"def solve(x):\n    if x < {lo}: return {lo}\n    if x > {hi}: return {hi}\n    return x"
        equiv = f"def solve(x):\n    return max({lo}, min({hi}, x))"
        bad = f"def solve(x):\n    if x < {lo}: return {lo}\n    if x > {hi + 1}: return {hi + 1}\n    return x"
        items.append(_make_item(f"clamp_{i}", "clamp", i, spec, good, equiv, bad))
    return items


def _gen_parity_sum(rng):
    ks = list(range(1, 13))
    rng.shuffle(ks)
    items = []
    for i, k in enumerate(ks):
        spec = {
            "task": f"parity of sum(xs)+{k}",
            "input_domain": {
                "type": "list[int]",
                "length_range": [0, 4],
                "element_range": [-2, 2]
            },
            "affine_offset_k": k,
        }
        good = f"def solve(xs):\n    return (sum(xs) + {k}) % 2"
        equiv = f"def solve(xs):\n    s=0\n    for x in xs:\n        s += x\n    return (s + {k}) % 2"
        bad = f"def solve(xs):\n    return (sum(xs) + {k} + 1) % 2"
        items.append(_make_item(f"parity_sum_{i}", "parity_sum", i, spec, good, equiv, bad))
    return items


def _gen_floor_div(rng):
    ds = list(range(2, 14))
    rng.shuffle(ds)
    items = []
    for i, d in enumerate(ds):
        spec = {
            "task": f"floor division x // {d}",
            "input_domain": {
                "type": "int",
                "range": [-25, 25]
            },
            "divisor_d": d,
        }
        good = f"def solve(x):\n    return x // {d}"
        equiv = f"def solve(x):\n    return divmod(x, {d})[0]"
        bad = f"def solve(x):\n    return int(x / {d})"
        items.append(_make_item(f"floor_div_{i}", "floor_div", i, spec, good, equiv, bad))
    return items


def _gen_interval_contains(rng):
    items = []
    used_pairs = set()
    for i in range(12):
        while True:
            lo = rng.randint(-10, 10)
            hi = rng.randint(-10, 10)
            if lo < hi and (lo, hi) not in used_pairs:
                used_pairs.add((lo, hi))
                break
        spec = {
            "task": "check if x in [lo,hi]",
            "input_domain": {
                "type": "int",
                "range": [-15, 15]
            },
            "lo": lo,
            "hi": hi,
        }
        good = f"def solve(x):\n    return {lo} <= x <= {hi}"
        equiv = f"def solve(x):\n    if x < {lo}: return False\n    if x > {hi}: return False\n    return True"
        bad = f"def solve(x):\n    return {lo} <= x < {hi}"
        items.append(_make_item(f"interval_contains_{i}", "interval_contains", i, spec, good, equiv, bad))
    return items


GENERATORS = [
    _gen_count_gt,
    _gen_shifted_sum,
    _gen_rotate_left,
    _gen_count_equal,
    _gen_clamp,
    _gen_parity_sum,
    _gen_floor_div,
    _gen_interval_contains,
]


def _oracle_solve(item):
    fam = item["family"]
    spec = item["specification"]
    if fam == "count_gt":
        c = spec["cutoff"]
        def _oracle(xs):
            count = 0
            for x in xs:
                if x > c:
                    count += 1
            return count
        return _oracle
    elif fam == "shifted_sum":
        k = spec["offset_k"]
        def _oracle(xs):
            s = 0
            for x in xs:
                s += x + k
            return s
        return _oracle
    elif fam == "rotate_left":
        k = spec["k"]
        def _oracle(xs):
            if not xs:
                return []
            n = len(xs)
            kk = k % n
            res = []
            for i in range(n):
                res.append(xs[(i + kk) % n])
            return res
        return _oracle
    elif fam == "count_equal":
        t = spec["target"]
        def _oracle(xs):
            count = 0
            for x in xs:
                if x == t:
                    count += 1
            return count
        return _oracle
    elif fam == "clamp":
        lo, hi = spec["lo"], spec["hi"]
        def _oracle(x):
            return sorted((lo, x, hi))[1]
        return _oracle
    elif fam == "parity_sum":
        k = spec["affine_offset_k"]
        def _oracle(xs):
            odd_count = 0
            for x in xs:
                if x % 2 != 0:
                    odd_count += 1
            return (odd_count + k) % 2
        return _oracle
    elif fam == "floor_div":
        d = spec["divisor_d"]
        def _oracle(x):
            return divmod(x, d)[0]
        return _oracle
    elif fam == "interval_contains":
        lo, hi = spec["lo"], spec["hi"]
        def _oracle(x):
            return x in range(lo, hi + 1)
        return _oracle
    raise ValueError(f"Unknown family {fam}")


def _test_cases(item):
    fam = item["family"]
    spec = item["specification"]
    if fam in ("count_gt", "shifted_sum", "parity_sum"):
        lo, hi = spec["input_domain"]["element_range"]
        cases = []
        for length in range(5):
            for combo in product(range(lo, hi + 1), repeat=length):
                cases.append(list(combo))
        return cases
    elif fam == "count_equal":
        t = spec["target"]
        lo, hi = t - 2, t + 2
        cases = []
        for length in range(5):
            for combo in product(range(lo, hi + 1), repeat=length):
                cases.append(list(combo))
        return cases
    elif fam == "rotate_left":
        lo, hi = -1, 1
        cases = []
        for length in range(7):
            for combo in product(range(lo, hi + 1), repeat=length):
                cases.append(list(combo))
        return cases
    elif fam == "clamp":
        lo, hi = -15, 15
        return [x for x in range(lo, hi + 1)]
    elif fam == "floor_div":
        lo, hi = -25, 25
        return [x for x in range(lo, hi + 1)]
    elif fam == "interval_contains":
        lo, hi = -15, 15
        return [x for x in range(lo, hi + 1)]
    raise ValueError(f"Unknown family {fam}")


def _sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _build_suite(out_dir: str):
    if os.path.exists(out_dir) and len(os.listdir(out_dir)) > 0:
        raise ValueError(f"Output directory {out_dir} must be absent or empty")

    rng = random.Random(2026100801)
    all_items = []
    for gen in GENERATORS:
        all_items.extend(gen(rng))

    audit_records = []
    for item in all_items:
        _check_candidate(item["code_good"])
        _check_candidate(item["code_equivalent"])
        _check_candidate(item["code_bad"])
        
        good_fn = _exec_candidate(item["code_good"])
        equiv_fn = _exec_candidate(item["code_equivalent"])
        bad_fn = _exec_candidate(item["code_bad"])
        oracle_fn = _oracle_solve(item)
        cases = _test_cases(item)

        mismatch_bad = 0
        witness = None

        for case in cases:
            o = oracle_fn(case)
            g = good_fn(case)
            e = equiv_fn(case)
            b = bad_fn(case)
            if g != o or e != o:
                raise RuntimeError(f"Good/equiv mismatch in {item['item_id']}")
            if b != o:
                mismatch_bad += 1
                if witness is None:
                    witness = {"input": case, "expected": o, "actual": b}

        if mismatch_bad == 0:
            raise RuntimeError(f"Bad candidate has zero mismatches: {item['item_id']}")

        audit_records.append({
            "item_id": item["item_id"],
            "oracle_case_count": len(cases),
            "mismatch_bad_count": mismatch_bad,
            "witness_bad": witness,
        })

    for item, audit in zip(all_items, audit_records):
        item.update(audit)

    os.makedirs(out_dir, exist_ok=True)

    items_path = os.path.join(out_dir, "items.jsonl")
    with open(items_path, "w") as f:
        for item in all_items:
            f.write(json.dumps(item, sort_keys=True) + "\n")

    audit_path = os.path.join(out_dir, "oracle_audit.json")
    with open(audit_path, "w") as f:
        json.dump(audit_records, f, indent=2, sort_keys=True)

    hashes = {
        "items_sha256": _sha256(open(items_path).read()),
        "audit_sha256": _sha256(open(audit_path).read()),
    }

    summary = {
        "total_items": len(all_items),
        "families": dict(Counter(i["family"] for i in all_items)),
        "hashes": hashes,
    }

    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    return all_items, audit_records


def _self_test():
    import tempfile
    import shutil

    tmp = tempfile.mkdtemp()
    try:
        items1, audit1 = _build_suite(tmp)

        ids = [i["item_id"] for i in items1]
        if len(ids) != 96 or len(set(ids)) != 96:
            raise AssertionError("Unique ID count mismatch")

        fam_counts = Counter(i["family"] for i in items1)
        if any(v != 12 for v in fam_counts.values()):
            raise AssertionError("Family quota mismatch")

        expected_counts = {
            "count_gt": 781,
            "shifted_sum": 781,
            "parity_sum": 781,
            "rotate_left": 1093,
            "count_equal": 781,
            "clamp": 31,
            "floor_div": 51,
            "interval_contains": 31,
        }

        for item, audit in zip(items1, audit1):
            if audit["mismatch_bad_count"] < 1:
                raise AssertionError(f"Bad candidate has zero mismatches: {item['item_id']}")
            if item["code_good"].strip() == item["code_equivalent"].strip():
                raise AssertionError(f"Good and equivalent are identical: {item['item_id']}")
            
            exp_count = expected_counts.get(item["family"])
            if exp_count is not None and audit["oracle_case_count"] != exp_count:
                raise AssertionError(f"Case count mismatch for {item['family']}: got {audit['oracle_case_count']}, expected {exp_count}")

        boundary_ok = False
        floor_ok = False
        neg_ok = False
        
        for item, audit in zip(items1, audit1):
            if item["family"] == "floor_div":
                w = audit.get("witness_bad")
                if w and isinstance(w.get("input"), int) and w["input"] < 0:
                    floor_ok = True
            
            cases = _test_cases(item)
            if any(isinstance(c, list) and len(c) == 0 for c in cases):
                boundary_ok = True
                
            if item["family"] == "clamp":
                if -15 in cases and 15 in cases:
                    neg_ok = True

        if not (boundary_ok and floor_ok and neg_ok):
            raise AssertionError("Coverage check failed")

        print("Self-test passed.")
    finally:
        shutil.rmtree(tmp)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, required=False)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
    else:
        if not args.out:
            raise ValueError("--out is required when not running --self-test")
        _build_suite(args.out)


if __name__ == "__main__":
    main()