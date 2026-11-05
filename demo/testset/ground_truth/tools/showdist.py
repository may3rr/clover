import json, sys
from pathlib import Path
from collections import OrderedDict
GT = Path('/Users/jackielyu/Coding/tmall/demo/testset/ground_truth')
p = json.load(open(GT/'pool/items.json'))
done = {json.loads(l)['unit_id'] for l in (GT/'labels.jsonl').open()}
paper = sys.argv[1]
groups = OrderedDict()
for x in p:
    if x['id'] in done or not x['stratum'].startswith('distribution') or not x['paper'].startswith(paper): continue
    d = next(a for a in x['alarms'] if a['label'].startswith('distribution'))
    k = (x['paper'], d['id'])
    groups.setdefault(k, []).append(x)
for (pp, fid), xs in groups.items():
    x = xs[0]
    d = next(a for a in x['alarms'] if a['label'].startswith('distribution'))
    print(f"{pp} {fid} | {(x['loc'].get('section') or '')[:30]} | {d['title']} | units: {' '.join(y['id'] for y in xs)}")
    for y in xs:
        for a in y['alarms']:
            if not a['label'].startswith('distribution'): print('   O:', y['id'], a['label'], a['title'][:80], (a['detail'] or '')[:100])
    print('   S:', x['sentence']['text'][:int(sys.argv[2]) if len(sys.argv)>2 else 350])
