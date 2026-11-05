import json, sys
from pathlib import Path
GT = Path('/Users/jackielyu/Coding/tmall/demo/testset/ground_truth')
p = json.load(open(GT/'pool/items.json'))
done = {json.loads(l)['unit_id'] for l in (GT/'labels.jsonl').open()}
prefix = sys.argv[1]; paper = sys.argv[2] if len(sys.argv) > 2 else None
for x in p:
    if x['id'] in done or not x['stratum'].startswith(prefix): continue
    if paper and not x['paper'].startswith(paper): continue
    print('='*100); print(x['id'], x['paper'], x['loc']['unit'], x['labels'])
    for a in x['alarms']:
        print('  ALARM', a['label'], a['severity'], '|', (a['detail'] or '').replace('\n',' ')[:400])
    if x['loc']['unit'][0] != 'ref':
        print('  SENT:', x['sentence']['text'][:500])
    for r in x['refs']:
        print('  REF', r['id'], r['raw'][:300])
        c = r['check']
        if c and x['loc']['unit'][0]=='ref':
            print('    CHECK', c['status'], c['issues'], '| M:', c['title'], c['authors'][:4] if c['authors'] else None, c['year'], c['venue'], c['doi'], c['source'])
