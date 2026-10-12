"""Compare every analysis field; whitelist only the documented analyzer-hash change."""
import argparse,hashlib,json,math
from pathlib import Path

def equal(expected,actual,path=''):
    assert type(expected) is type(actual),('TYPE_MISMATCH',path)
    if isinstance(expected,dict):
        assert expected.keys()==actual.keys(),('KEY_MISMATCH',path)
        for k in expected:equal(expected[k],actual[k],path+'/'+k)
    elif isinstance(expected,list):
        assert len(expected)==len(actual),('LENGTH_MISMATCH',path)
        for i,(a,b) in enumerate(zip(expected,actual)):equal(a,b,path+'/'+str(i))
    elif isinstance(expected,float):
        assert math.isfinite(expected) and math.isfinite(actual) and math.isclose(expected,actual,rel_tol=1e-12,abs_tol=1e-12),('NUMBER_MISMATCH',path)
    else:assert expected==actual,('VALUE_MISMATCH',path)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--expected',type=Path,required=True);ap.add_argument('--actual',type=Path,required=True);args=ap.parse_args()
    expected=json.loads(args.expected.read_text());actual=json.loads(args.actual.read_text())
    version={'dc-v6-analysis-v1':'v6','dc-v7-analysis-v1':'v7'}[expected['schema']]
    mapping=json.loads((args.root/'EXPORT_PROVENANCE.json').read_text())['analysis_sources'][version]
    source=args.root/'scripts'/f'analyze_{version}.py'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==mapping['public_sha256'],'PUBLIC_ANALYZER_DRIFT'
    assert expected['inputhashes']['analyzer_sha256']==mapping['original_sha256'],'ORIGINAL_ANALYZER_ID'
    assert actual['inputhashes']['analyzer_sha256']==mapping['public_sha256'],'PUBLIC_ANALYZER_ID'
    del expected['inputhashes']['analyzer_sha256'];del actual['inputhashes']['analyzer_sha256']
    equal(expected,actual)
    print(json.dumps({'status':'PASS_REPRODUCED_ANALYSIS','version':version,'float_tolerance':1e-12,
        'scope':'All keys, types, counts, coverage, verdicts, input hashes and numerical values checked. Only the verified analyzer-source hash substitution is excluded. This verifies reproduction, not scientific generalization.'}))

if __name__=='__main__':main()
