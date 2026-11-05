import json, sys
from pathlib import Path
GT = Path('/Users/jackielyu/Coding/tmall/demo/testset/ground_truth')
items = json.load(open(GT / 'pool/items.json'))
done = {json.loads(l)['unit_id'] for l in (GT/'labels.jsonl').open()} if (GT/'labels.jsonl').exists() else set()
from collections import Counter
c = Counter((x['paper'], x['stratum'][:20]) for x in items if x['id'] not in done)
for k, v in sorted(c.items()): print(v, k)
print(sum(c.values()), 'left')
