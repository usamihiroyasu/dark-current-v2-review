"""Offline metadata checks only; no model calls or statistical inference."""
from pathlib import Path
from collections import Counter
import hashlib, json

FIELDS = {'call_id','config_id','criterion','order','pair_type','task_id','timestamp_utc','request_sha256','raw_response_sha256','served_model','simulation_fixture','valid','winner','finish_reason','error_class','latency_seconds','usage','manifest_sha256'}
CONDITIONS = {('neutral','dc_core_clone','IDENTICAL'),('strict','dc_core_clone','IDENTICAL'),('neutral','signal_chosen_vs_rejected','AB'),('neutral','signal_chosen_vs_rejected','BA'),('strict','signal_chosen_vs_rejected','AB'),('strict','signal_chosen_vs_rejected','BA')}
INVALID = {('neutral','dc_core_clone','IDENTICAL'):0,('strict','dc_core_clone','IDENTICAL'):0,('neutral','signal_chosen_vs_rejected','AB'):0,('neutral','signal_chosen_vs_rejected','BA'):0,('strict','signal_chosen_vs_rejected','AB'):0,('strict','signal_chosen_vs_rejected','BA'):0}

def verify(rows, config, analysis):
    assert len(rows)==2910 and len({r['call_id'] for r in rows})==2910
    tasks={r['task_id'] for r in rows}; assert len(tasks)==485
    assert config['planned_tasks']==485 and config['planned_calls']==2910
    assert config['invalid_ceiling']==.01 and config['criterion_holm_family_size']==2
    assert config['parser_rescue'] is False and config['forced_json_schema'] is False
    groups=Counter(); invalid=Counter()
    for r in rows:
        assert set(r)==FIELDS and type(r['valid']) is bool
        assert r['config_id']=='qwen35-local-q4km-raw' and r['served_model']=='qwen3.5:35b-a3b'
        assert r['simulation_fixture'] is False and r['error_class'] is None and r['finish_reason']=='stop'
        assert r['manifest_sha256']==config['source_manifest_sha256']
        assert r['winner'] in ('A','B','tie') if r['valid'] else r['winner'] is None
        key=(r['criterion'],r['pair_type'],r['order']);assert key in CONDITIONS
        groups[(r['task_id'],key)]+=1;invalid[key]+=not r['valid']
    assert all(groups[(t,k)]==1 for t in tasks for k in CONDITIONS)
    assert {k:invalid[k] for k in CONDITIONS}==INVALID
    op=analysis['operational']['qwen35-local-q4km-raw']
    assert op['planned']==op['completed']==2910 and op['invalid']==0 and op['status']=='PASS'
    assert op['invalid_fraction']==0.0 and op['invalid_fraction']<=config['invalid_ceiling']
    assert len(analysis['cells'])==2 and {c['criterion'] for c in analysis['cells']}=={'neutral','strict'}
    for c in analysis['cells']:
        assert c['status']=='PASS_USEFUL_LOW_DC'
        assert c['clone']['observed_adverse']==0
        assert c['clone']['planned']==485
        assert c['utility']['planned_tasks']==485 and c['utility']['planned_calls']==970
    cost={k:sum(r['usage'][k] for r in rows) for k in ('prompt_tokens','completion_tokens')}
    assert cost=={'prompt_tokens':2477434,'completion_tokens':17460}
    assert cost==analysis['usage']['qwen35-local-q4km-raw']['known_token_sums']
    return {'status':'PASS_SAVED_METADATA_CHECKS_ONLY','tasks':485,'terminals':2910,'valid':2910,'invalid':0,'scientific_certificates_recomputed':0,'new_model_calls':0,'usage':cost}

def guard(rows, calls, config, analysis, selected):
    import math
    call_fields = {'call_id','candidate_a_role','candidate_b_role','criterion','expected_canonical_choice','expected_display_choice','order','pair_id','pair_type','source_row_idx','source_subset','task_id','prompt_sha256','candidate_a_sha256','candidate_b_sha256'}
    assert len(calls)==2910 and len({c['call_id'] for c in calls})==2910
    byid={c['call_id']:c for c in calls}; assert {r['call_id'] for r in rows}==set(byid)
    task_subsets={}
    assert len(selected)==485 and len({x['task_id'] for x in selected})==485
    selected_by_task={x['task_id']:x for x in selected}
    for r in rows:
        c=byid[r['call_id']];assert set(c)==call_fields
        assert all(r[k]==c[k] for k in ('call_id','task_id','criterion','pair_type','order'))
        assert c['expected_display_choice']=={'IDENTICAL':'tie','AB':'A','BA':'B'}[c['order']]
        assert c['source_subset'] in config['subset_counts'] and type(c['source_row_idx']) is int
        source=selected_by_task[c['task_id']]
        assert c['source_row_idx']==source['row'] and c['source_subset']==source['subset']
        assert c['task_id']==f"rb2hold:{source['subset']}:{source['id']}"
        assert task_subsets.setdefault(c['task_id'],c['source_subset'])==c['source_subset']
        assert type(r['latency_seconds']) in (int,float) and math.isfinite(r['latency_seconds']) and r['latency_seconds']>=0
        assert set(r['usage'])=={'prompt_tokens','completion_tokens'} and all(type(v) is int and v>=0 for v in r['usage'].values())
        for key in ('request_sha256','raw_response_sha256','manifest_sha256'):
            assert type(r[key]) is str and len(r[key])==64 and set(r[key])<=set('0123456789abcdef')
    assert dict(Counter(task_subsets.values()))==config['subset_counts']
    for cell in analysis['cells']:
        signal=[r for r in rows if r['criterion']==cell['criterion'] and r['pair_type']=='signal_chosen_vs_rejected']
        correct=sum(r['valid'] and r['winner']==byid[r['call_id']]['expected_display_choice'] for r in signal)
        assert len(signal)==970 and correct/970==cell['utility']['mean']
        for order in ('AB','BA'):
            chosen=[r for r in signal if r['order']==order]
            assert len(chosen)==485 and sum(r['winner']==byid[r['call_id']]['expected_display_choice'] for r in chosen)==cell['utility']['by_order'][order]['correct']


if __name__=='__main__':
    root=Path(__file__).resolve().parent
    config=json.loads((root/'CONFIGURATION_AND_GATE.json').read_text())
    for name,key in [('records.jsonl','records_sha256'),('OBSERVED_ANALYSIS.json','observed_analysis_sha256'),('calls_metadata.jsonl','calls_metadata_sha256'),('selected_metadata.jsonl','selected_metadata_sha256'),('proxy_metadata.jsonl','proxy_metadata_sha256')]:
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==config[key]
    rows=[json.loads(line) for line in (root/'records.jsonl').read_text().split('\n') if line]
    analysis=json.loads((root/'OBSERVED_ANALYSIS.json').read_text())
    calls=[json.loads(line) for line in (root/'calls_metadata.jsonl').read_text().split('\n') if line]
    selected=[json.loads(line) for line in (root/'selected_metadata.jsonl').read_text().split('\n') if line]
    guard(rows,calls,config,analysis,selected)
    print(json.dumps(verify(rows,config,analysis),sort_keys=True))
