"""Independent post-hoc check of planted test contracts; never changes frozen files."""
import ast, hashlib, itertools, json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def specification(row, x):
    s, f = row['specification'], row['family']
    if f == 'count_gt': return sum(int(v > s['cutoff']) for v in x)
    if f == 'count_equal': return sum(int(v == s['target']) for v in x)
    if f == 'shifted_sum': return sum(v + s['offset_k'] for v in x)
    if f == 'rotate_left':
        k = s['k'] % len(x) if x else 0
        return x[k:] + x[:k]
    if f == 'clamp': return max(s['lo'], min(x, s['hi']))
    if f == 'parity_sum': return (sum(x) + s['affine_offset_k']) % 2
    if f == 'floor_div': return x // s['divisor_d']
    if f == 'interval_contains': return s['lo'] <= x <= s['hi']
    raise ValueError(f)

def main():
    items = {r['item_id']: r for r in map(json.loads, (ROOT/'v6_frozen/items.jsonl').read_text().splitlines())}
    data = ROOT/'controlled_gates_results'
    rows = list(map(json.loads, (data/'candidates.jsonl').read_text().splitlines()))
    counts, table, semantic_table = Counter(), Counter(), Counter()
    seen = set()
    for r in rows:
        key = (r['item_id'], r['group']); assert key not in seen; seen.add(key)
        item = items[r['item_id']]; tree = ast.parse(r['program'])
        base = ast.parse(item[r['code_key']]); assert ast.dump(tree.body[0]) == ast.dump(base.body[0])
        assert len(tree.body) == len(base.body) + 3 and all(isinstance(a, ast.Assert) for a in tree.body[-3:])
        assert r['program_sha256'] == hashlib.sha256(r['program'].encode()).hexdigest()
        inputs, labels = [], []
        for a in tree.body[-3:]:
            t = a.test
            assert isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)
            assert isinstance(t.left, ast.Call) and t.left.func.id == 'solve' and len(t.left.args) == 1
            inputs.append(ast.literal_eval(t.left.args[0])); labels.append(ast.literal_eval(t.comparators[0]))
        assert inputs == r['test_cases'] and labels == r['test_labels'] and len(set(map(repr, inputs))) == 3
        d = item['specification']['input_domain']
        if d['type'] == 'int': cases = list(range(d['range'][0], d['range'][1]+1))
        else:
            cases = [list(v) for n in range(d['length_range'][0], d['length_range'][1]+1)
                     for v in itertools.product(range(d['element_range'][0], d['element_range'][1]+1), repeat=n)]
        assert all(x in cases for x in inputs)
        namespace = {}; exec(compile(ast.Module(body=base.body, type_ignores=[]), '<trusted-template>', 'exec'), namespace)
        correct = all(namespace['solve'](x) == specification(item, x) for x in cases)
        assert correct == r['semantic_finite_validity']
        predicted_execution = all(namespace['solve'](x) == y for x, y in zip(inputs, labels))
        assert r['GS'] and r['GE'] == predicted_execution == (r['returncode'] == 0 and r['marker'])
        independent_labels = all(y == specification(item, x) for x, y in zip(inputs, labels))
        if r['group'] != 'bad_self_consistent': assert independent_labels
        counts[r['group']] += 1
        table[f"GS=1,GE={int(r['GE'])}"] += 1
        semantic_table[f"GE={int(r['GE'])},semantic={int(correct)}"] += 1
    summary = json.loads((data/'summary.json').read_text())
    assert counts == summary['group_counts'] and table == summary['GS_GE_table'] and semantic_table == summary['GE_semantic_table']
    assert len(rows) == 456 and len(seen) == 456
    result = {'status':'PASS_INDEPENDENT_PLANTED_CONTRACT_CHECK','programs':len(rows),
              'group_counts':dict(counts),'GE_semantic_table':dict(semantic_table),
              'candidate_sha256':hashlib.sha256((data/'candidates.jsonl').read_bytes()).hexdigest(),
              'verification':'AST-derived assertion inputs/labels; independent direct specification over full domains; recorded subprocess verdicts reconciled. No execution or latency repeated.'}
    (ROOT/'CONTROLLED_GATES_VERIFICATION.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))

if __name__ == '__main__': main()
