import json, sys
from pathlib import Path
GT = Path('/Users/jackielyu/Coding/tmall/demo/testset/ground_truth')
p = json.load(open(GT/'pool/items.json'))
done = {json.loads(l)['unit_id'] for l in (GT/'labels.jsonl').open()}
paper = sys.argv[1]; strat = sys.argv[2] if len(sys.argv) > 2 else 'support'
only = sys.argv[3].split(',') if len(sys.argv) > 3 else None
for x in p:
    if x['id'] in done or not x['stratum'].startswith(strat) or not x['paper'].startswith(paper): continue
    if only and x['id'] not in only: continue
    print('='*110); print(x['id'], x['paper'], '|', (x['loc'].get('section') or '')[:30], x['loc'].get('tex'), x['loc']['unit'])
    print('SENT:', x['sentence']['text'][:600])
    for a in x['alarms']:
        print('  ALARM', a['label'][:40], a['severity'], a['id'], '|', (a['detail'] or '').replace('\n',' ')[:300])
    for r in x['refs']:
        print('  REF', r['id'], r['label'], '|', r['raw'][:200])
        for s in r['support']:
            print(f"    -> {s['label']} off={s['off_topic']} kind={s['source_kind']} src={(s['source_link'] or {}).get('label')}")
            print('       EV:', (s['evidence'] or '')[:400])
            print('       RAT:', (s['rationale'] or '')[:500])
