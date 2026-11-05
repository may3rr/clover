import json, sys
from pathlib import Path
GT = Path('/Users/jackielyu/Coding/tmall/demo/testset/ground_truth')
p = json.load(open(GT/'pool/items.json'))
done = {json.loads(l)['unit_id'] for l in (GT/'labels.jsonl').open()}
paper = sys.argv[1]; only = sys.argv[2].split(',') if len(sys.argv) > 2 else None
for x in p:
    if x['id'] in done or not x['stratum'].startswith('support') or not x['paper'].startswith(paper): continue
    if only and x['id'] not in only: continue
    print('='*90); print(x['id'], x['loc'].get('tex'), '| SENT:', x['sentence']['text'][:420])
    flagged = set()
    for a in x['alarms']:
        if a['label'].startswith('label:'): flagged.add(a['id'].split('/')[1]); continue
        print('  ALARM', a['label'][:30], a['severity'], a['id'], '|', (a['detail'] or '').replace('\n',' ')[:220])
    for r in x['refs']:
        for s in r['support']:
            if s['label'] in ('unsupported',) or s['off_topic'] or r['id'] in flagged:
                print(f"  REF {r['id']} [{r['label']}] {r['raw'][:110]}")
                print(f"    -> {s['label']} off={s['off_topic']} {s['source_kind']} {(s['source_link'] or {}).get('label','')[:90]}")
                print('       EV:', (s['evidence'] or '')[:260])
