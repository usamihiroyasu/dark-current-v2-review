"""Offline V8 analysis. No model requests; source and journal verification first."""
import argparse
import importlib.util
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
from v8_stats_helpers import read_json, sha, binom_cdf, cp_upper, holm, bootstrap
NAMESPACE = "V8-benchmark-bridge-20261009"


def load_lines(path):
    return [read_json(line) for line in path.read_text().split("\n") if line.strip()]



def parse_verdict(content):
    def unique_object(pairs):
        if len(pairs) != len({k for k, _ in pairs}):
            raise ValueError("DUPLICATE_KEY")
        return dict(pairs)
    try:
        obj = json.loads(content, object_pairs_hook=unique_object)
        if isinstance(obj, dict) and set(obj) == {"winner"} and obj["winner"] in ("A", "B", "tie"):
            return obj["winner"]
        return None
    except (ValueError, TypeError):
        return None

def analyze(root, run, replicates=20000):
    root = Path(root).resolve()
    assert Path(run).resolve() == root, 'OFFLINE_ROOT_ONLY'
    export = read_json((root/'EXPORT_PROVENANCE.json').read_text())
    for name, expected_hash in export['files'].items():
        p=root/name
        assert p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root), 'SOURCE_BOUNDARY'
        assert sha(p.read_bytes())==expected_hash, 'EXPORT_DRIFT:'+name
    assert sha(Path(__file__).read_bytes())==export['files']['analyze_v8_public.py'], 'ANALYZER_IDENTITY'
    assert sha(Path(sys.modules['v8_stats_helpers'].__file__).read_bytes())==export['files']['v8_stats_helpers.py'], 'HELPER_IDENTITY'
    manifest_bytes=(root/'manifest.json').read_bytes(); mh=sha(manifest_bytes)
    manifest=read_json(manifest_bytes); configs=manifest['configs']
    calls=load_lines(root/'calls_metadata.jsonl')
    assert len(calls)==612 and len({c['call_id'] for c in calls})==612, 'CALL_COVERAGE'
    by={}
    expected_cells={('dc_core_clone',c,'IDENTICAL') for c in ('neutral','strict')}|{('signal_chosen_vs_rejected',c,o) for c in ('neutral','strict') for o in ('AB','BA')}
    for c in calls:
        by.setdefault(c['task_id'],[]).append(c)
        if c['pair_type']=='dc_core_clone': assert c['expected_display_choice']=='tie', 'CLONE_LABEL'
        else: assert c['expected_display_choice']==('A' if c['candidate_a_role']=='chosen' else 'B'), 'SIGNAL_LABEL'
    assert len(by)==102 and all(len(g)==6 and {(c['pair_type'],c['criterion'],c['order']) for c in g}==expected_cells for g in by.values()), 'FACTORIAL'
    journal_bytes=(root/'journal.jsonl').read_bytes()
    progress=read_json((root/'progress.json').read_text()); fixture=progress['simulation_fixture']
    assert fixture is False and replicates==20000 and progress['status']=='COMPLETE' and progress['completed']==progress['planned']==1224 and progress['manifest_sha256']==mh, 'COMPLETE_REAL_STUDY_ONLY'
    records=[read_json(x) for x in journal_bytes.decode().split('\n') if x.strip()]
    expected=[(cfg,c) for cfg in configs for c in sorted(calls,key=lambda c:sha((NAMESPACE+c['call_id']).encode()))]
    assert len(records)==2448, 'JOURNAL_COVERAGE'
    terminals={}; pending=Counter()
    for i,(cfg,c) in enumerate(expected):
        a,b=records[2*i:2*i+2]
        assert a['type']=='intent' and b['type']=='terminal', 'INTENT_TERMINAL'
        for k in ('call_id','task_id','pair_type','criterion','order'):
            assert a[k]==b[k]==c[k], 'SLOT_JOIN:'+k
        for k in ('manifest_sha256','request_sha256','timestamp_utc','simulation_fixture','config_id'):
            assert a[k]==b[k], 'INTENT_JOIN:'+k
        assert b['manifest_sha256']==mh and b['config_id']==cfg['id'] and b['simulation_fixture'] is False, 'RUN_IDENTITY'
        v=parse_verdict(b['content'])
        valid=v is not None and b['finish_reason']=='stop' and b['served_model']==cfg['served_model'] and b['error_class'] is None
        assert b['valid'] is valid and b['winner']==(v if valid else None), 'VERDICT'
        key=(cfg['id'],c['call_id']); assert key not in terminals, 'DUPLICATE'
        terminals[key]=b
    operational, usage = {}, {}
    for cfg in configs:
        cid = cfg['id']
        observed = [r for (c, _), r in terminals.items() if c == cid]
        invalid = sum(not r['valid'] for r in observed)
        identity = all(r['served_model'] == cfg['served_model'] for r in observed) and len(observed) == 612
        ok = len(observed) == 612 and pending[cid] == 0 and identity and invalid / 612 <= .01
        operational[cid] = dict(planned=612, completed=len(observed), missing=612-len(observed), invalid=invalid,
                                ambiguous_intents=pending[cid], served_identity_complete=identity,
                                invalid_fraction=invalid/612 if len(observed)==612 else None,
                                status='PASS' if ok else 'HOLD', errors=dict(Counter(r['error_class'] for r in observed if r['error_class'])))
        total = {'prompt_tokens': 0, 'completion_tokens': 0}
        missing = 0
        for r in observed:
            u = r['usage']
            complete = isinstance(u, dict)
            for k in total:
                value = u.get(k) if isinstance(u, dict) else None
                if type(value) is int and value >= 0:
                    total[k] += value
                else:
                    complete = False
            missing += not complete
        usage[cid] = dict(known_token_sums=total, rows_missing_either_usage_field=missing,
                          observed_terminals=len(observed), latency_median_seconds=statistics.median(r['latency_seconds'] for r in observed) if observed else None)

    cells, task_values, family = [], {}, []
    for cfg in configs:
        cid = cfg['id']
        ok = operational[cid]['status'] == 'PASS'
        for crit in ('neutral', 'strict'):
            clone = [c for c in calls if c['pair_type'] == 'dc_core_clone' and c['criterion'] == crit]
            signal = [c for c in calls if c['pair_type'] == 'signal_chosen_vs_rejected' and c['criterion'] == crit]
            cr = [terminals.get((cid, c['call_id'])) for c in clone]
            sr = [terminals.get((cid, c['call_id'])) for c in signal]
            adverse = sum(r is not None and (not r['valid'] or r['winner'] != 'tie') for r in cr)
            clone_stats = dict(planned=102, completed=sum(r is not None for r in cr), invalid=sum(r is not None and not r['valid'] for r in cr),
                               observed_adverse=adverse, rate=adverse/102 if ok else None, upper_one_sided_95=cp_upper(adverse,102) if ok else None,
                               raw_p=binom_cdf(adverse,102,.05) if ok else 1.0, holm_p=None, gate=None)
            vals, strata = {}, {}
            order_counts = {}
            for order in ('AB', 'BA'):
                subset = [c for c in signal if c['order'] == order]
                obs = [terminals.get((cid, c['call_id'])) for c in subset]
                order_counts[order] = dict(planned=102, completed=sum(r is not None for r in obs),
                                          correct=sum(r is not None and r['valid'] and r['winner']==c['expected_display_choice'] for c,r in zip(subset,obs)))
            if ok:
                for tid in sorted({c['task_id'] for c in signal}):
                    pair = [c for c in signal if c['task_id']==tid]
                    vals[tid] = statistics.fmean(float(terminals[(cid,c['call_id'])]['valid'] and terminals[(cid,c['call_id'])]['winner']==c['expected_display_choice']) for c in pair)
                    strata.setdefault(pair[0]['source_subset'], []).append(vals[tid])
                assert len(vals)==102 and len(strata)==6 and all(len(s)==17 for s in strata.values()), 'UTILITY_STRATA'
                seed = int(sha((NAMESPACE+'|utility|'+cid+'|'+crit).encode()),16)
                boot = bootstrap([strata[s] for s in sorted(strata)], seed, replicates)
                task_values[(cid,crit)] = vals
            else:
                boot = None
            utility = dict(planned_calls=204, planned_tasks=102, completed=sum(r is not None for r in sr),
                           invalid=sum(r is not None and not r['valid'] for r in sr), by_order=order_counts,
                           mean=statistics.fmean(vals.values()) if ok else None,
                           stratum_means={s:statistics.fmean(v) for s,v in sorted(strata.items())} if ok else None,
                           bootstrap=boot, gate=boot['lower_one_sided_95']>=.75 if ok else None)
            cells.append(dict(config_id=cid,criterion=crit,status='PENDING' if ok else 'HOLD',clone=clone_stats,utility=utility))
            family.append(clone_stats['raw_p'])
    for cell, adjusted in zip(cells, holm(family)):
        cell['clone']['holm_p'] = adjusted
        if cell['status'] != 'HOLD':
            cell['clone']['gate'] = cell['clone']['upper_one_sided_95'] <= .05 and adjusted <= .05
            cell['status'] = 'PASS_USEFUL_LOW_DC' if cell['clone']['gate'] and cell['utility']['gate'] else 'FAIL'

    paired, parser_diagnostic = {}, {}
    for cfg in configs:
        cid=cfg['id']
        if operational[cid]['status']=='PASS':
            n,s = task_values[(cid,'neutral')],task_values[(cid,'strict')]
            paired[cid]=dict(status='DESCRIPTIVE',tasks=102,strict_minus_neutral=statistics.fmean(s[t]-n[t] for t in n))
        else:
            paired[cid]=dict(status='HOLD',tasks=None,strict_minus_neutral=None)
        aligned, discrepant = 0,0
        for (c,_),r in terminals.items():
            if c!=cid: continue
            old=None
            try:
                obj=json.loads(r['content'])
                if isinstance(obj,dict) and set(obj)=={'winner'} and obj['winner'] in ('A','B','tie'): old=obj['winner']
            except (ValueError,TypeError): pass
            eligible = r['finish_reason']=='stop' and r['served_model']==cfg['served_model'] and r['error_class'] is None
            aligned += eligible and old is not None
            discrepant += eligible and old is not None and parse_verdict(r['content']) is None
        parser_diagnostic[cid]=dict(legacy_aligned_valid=aligned,legacy_valid_strict_invalid=discrepant,primary_reclassification=False)
    return dict(schema='dc-v8-benchmark-bridge-analysis-v1',simulation_fixture=fixture,
                scientific_scope='Crossconfiguration re-evaluation on previously used 102 benchmark rows; not fresh items, no human semantic-equivalence validation, no isolated domain/rubric/model causal effect.',
                interval_scope='Exact clone bounds assume independent Bernoulli units; stratified task bootstrap describes this fixed benchmark cohort. Degenerate intervals do not certify unseen populations.',
                journal_status=progress['status'],operational=operational,cells=cells,paired_criterion_descriptive=paired,
                usage=usage,parser_diagnostic=parser_diagnostic,holm_family_size=4,
                inputs=dict(manifest_sha256=mh,journal_sha256=sha(journal_bytes),analyzer_sha256=sha(Path(__file__).read_bytes()),
                            helpers_sha256=manifest['files']['v8_stats_helpers.py'],progress_sha256=sha((run/'progress.json').read_bytes()),source_hashes=manifest['files']))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--replicates',type=int,default=20000)
    a=p.parse_args()
    assert not a.out.exists() and a.out.parent.is_dir(), 'OUTPUT_BOUNDARY'
    result=analyze(a.root,a.run,a.replicates)
    with a.out.open('x') as f: json.dump(result,f,indent=2,allow_nan=False); f.write('\n')
    print(json.dumps({'analysis':str(a.out),'sha256':sha(a.out.read_bytes()),'fixture':result['simulation_fixture'],'cells':[c['status'] for c in result['cells']]}))


if __name__=='__main__': main()
