"""Offline metadata checks only; no model calls or statistical inference."""
from pathlib import Path
from collections import Counter
import hashlib, json

FIELDS = {'call_id','config_id','criterion','order','pair_type','task_id','timestamp_utc','request_sha256','raw_response_sha256','served_model','simulation_fixture','valid','winner','finish_reason','error_class','latency_seconds','usage','manifest_sha256'}
CONDITIONS = {('neutral','dc_core_clone','IDENTICAL'),('strict','dc_core_clone','IDENTICAL'),('neutral','signal_chosen_vs_rejected','AB'),('neutral','signal_chosen_vs_rejected','BA'),('strict','signal_chosen_vs_rejected','AB'),('strict','signal_chosen_vs_rejected','BA')}
INVALID = {('neutral','dc_core_clone','IDENTICAL'):22,('strict','dc_core_clone','IDENTICAL'):0,('neutral','signal_chosen_vs_rejected','AB'):85,('neutral','signal_chosen_vs_rejected','BA'):81,('strict','signal_chosen_vs_rejected','AB'):13,('strict','signal_chosen_vs_rejected','BA'):10}

def verify(rows, config, analysis):
    assert len(rows)==612 and len({r['call_id'] for r in rows})==612
    tasks={r['task_id'] for r in rows}; assert len(tasks)==102
    assert config['planned_tasks']==102 and config['planned_calls']==612
    assert config['invalid_ceiling']==.01 and config['criterion_holm_family_size']==2
    assert config['parser_rescue'] is False and config['forced_json_schema'] is False
    groups=Counter(); invalid=Counter()
    for r in rows:
        assert set(r)==FIELDS and type(r['valid']) is bool
        assert r['config_id']=='devstral-small2-ollama-q4km' and r['served_model']=='devstral-small-2:latest'
        assert r['simulation_fixture'] is False and r['error_class'] is None and r['finish_reason']=='stop'
        assert r['manifest_sha256']==config['source_manifest_sha256']
        assert r['winner'] in ('A','B','tie') if r['valid'] else r['winner'] is None
        key=(r['criterion'],r['pair_type'],r['order']);assert key in CONDITIONS
        groups[(r['task_id'],key)]+=1;invalid[key]+=not r['valid']
    assert all(groups[(t,k)]==1 for t in tasks for k in CONDITIONS)
    assert {k:invalid[k] for k in CONDITIONS}==INVALID
    op=analysis['operational']['devstral-small2-ollama-q4km']
    assert op['planned']==op['completed']==612 and op['invalid']==211 and op['status']=='HOLD'
    assert op['invalid_fraction']==211/612 and op['invalid_fraction']>config['invalid_ceiling']
    assert len(analysis['cells'])==2 and {c['criterion'] for c in analysis['cells']}=={'neutral','strict'}
    for c in analysis['cells']:
        assert c['status']=='HOLD'
        assert all(c['clone'][k] is None for k in ('rate','upper_one_sided_95','gate'))
        assert all(c['utility'][k] is None for k in ('mean','bootstrap','gate'))
    cost={k:sum(r['usage'][k] for r in rows) for k in ('prompt_tokens','completion_tokens')}
    assert cost=={'prompt_tokens':485592,'completion_tokens':4517}
    assert cost==analysis['usage']['devstral-small2-ollama-q4km']['known_token_sums']
    return {'status':'PASS_SAVED_OPERATIONAL_HOLD_METADATA','tasks':102,'terminals':612,'valid':401,'invalid':211,'scientific_certificates':0,'new_model_calls':0,'usage':cost}

if __name__=='__main__':
    root=Path(__file__).resolve().parent
    config=json.loads((root/'CONFIGURATION_AND_GATE.json').read_text())
    for name,key in [('records.jsonl','records_sha256'),('OBSERVED_ANALYSIS.json','observed_analysis_sha256')]:
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==config[key]
    rows=[json.loads(line) for line in (root/'records.jsonl').read_text().split('\n') if line]
    print(json.dumps(verify(rows,config,json.loads((root/'OBSERVED_ANALYSIS.json').read_text())),sort_keys=True))
