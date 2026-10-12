"""Reaggregate sanitized recorded evidence; never execute historical candidates."""
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args()
    rows=[json.loads(s) for s in (args.root/'sanitized_rows.jsonl').read_text().splitlines()]
    assert len(rows)==len({r['candidate_index'] for r in rows})==580
    assert len({(r['task_id'],r['sample_index']) for r in rows})==580
    cells=Counter();tasks=defaultdict(list);rc=Counter()
    for r in rows:
        assert type(r['parse_error_present']) is bool
        gs=not r['parse_error_present'] and r['n_real_asserts']>=3
        ge=(r['executed_in_sandbox'] and r['candidate_return_code']==0 and r['postlude_seen']
            and r['exit_kind']=='NORMAL' and r['docker_return_code']==0
            and not r['infrastructure_error'] and not r['timed_out'])
        assert (gs,ge)==(r['GS'],r['GE'])
        cells[f'GS={int(gs)},GE={int(ge)}']+=1;tasks[r['task_id']].append(ge);rc[str(r['candidate_return_code'])]+=1
    assert len(tasks)==145 and all(len(v)==4 for v in tasks.values())
    old=json.loads((args.root/'REANALYSIS.json').read_text())
    hist={str(k):v for k,v in Counter(map(sum,tasks.values())).items()}
    assert dict(cells)==old['table'] and hist==old['task_GE_histogram'] and dict(rc)==old['candidate_return_code_counts']
    diag=json.loads((args.root/'sanitized_oracle_diagnostic.json').read_text())
    assert len(diag)==len({r['task_sha256'] for r in diag})==40
    healthy=sum(r['oracle_healthy_recorded'] for r in diag)
    joint=sum(r['q38_pass_recorded'] and r['coder_pass_recorded'] for r in diag)
    discord=sum(r['q38_pass_recorded']!=r['coder_pass_recorded'] for r in diag)
    assert all(r['entered_resampling']==(r['oracle_healthy_recorded'] and not r['q38_pass_recorded'] and not r['coder_pass_recorded']) for r in diag)
    residual=sum(r['entered_resampling'] for r in diag)
    resampled=[r for r in diag if r['entered_resampling']]
    assert all(r['resample_q38_tries_recorded']==r['resample_coder_tries_recorded']==4 for r in resampled)
    recovered=sum(r['resample_q38_pass_recorded'] or r['resample_coder_pass_recorded'] for r in resampled)
    receipt=json.loads((args.root/'ORACLE_DIAGNOSTIC_REANALYSIS.json').read_text())
    assert [healthy,joint,discord,residual]==[receipt[k] for k in ('recorded_oracle_healthy','joint_pass','discordant','residual')]==[20,4,0,16]
    assert recovered==receipt['resample_pass']==0
    print(json.dumps({'status':'PASS_SANITIZED_REAGGREGATION','table':dict(cells),'task_GE_histogram':hist,
        'diagnostic':[healthy,joint,discord,residual,recovered],
        'scope':'Recorded predicates only. No historical execution, oracle completeness, or raw v1 join reconstruction from this derivative.'}))

if __name__=='__main__':main()
