"""Append labels. Usage: python lab.py BATCHFILE
BATCHFILE holds lines:  L(uid, verdict, cause, evidence, note, sel=None, sev=True)
sel picks alarms by substring of label/title/id; sel=None covers the rest."""
import json, sys
from collections import defaultdict
from pathlib import Path
GT = Path('/Users/jackielyu/Coding/tmall/demo/testset/ground_truth')
items = {x['id']: x for x in json.load(open(GT / 'pool/items.json'))}
out = GT / 'labels.jsonl'
done = set()
if out.exists():
    for ln in out.open():
        if ln.strip(): done.add(json.loads(ln)['unit_id'])
specs = defaultdict(list)
def L(uid, verdict, cause, evidence, note, sel=None, sev=True, sub=None):
    assert uid in items, uid
    assert verdict in {'true_issue', 'false_alarm', 'debatable', 'cannot_judge'}, verdict
    specs[uid].append(dict(verdict=verdict, cause=cause, evidence=evidence, note=note, sel=sel, sev=sev, sub=sub))
exec(open(sys.argv[1]).read())
n = 0
recs = []
if True:
    for uid, ss in specs.items():
        if uid in done:
            print('skip', uid); continue
        x = items[uid]
        sent = x['sentence']['text']
        for a in x['alarms']:
            hay = a['label'] + '|' + a['title'] + '|' + str(a['id'])
            s = next((s for s in ss if s['sel'] and s['sel'] in hay), None) or \
                next((s for s in ss if s['sel'] is None), None)
            if s is None:
                raise SystemExit(f'{uid}: no spec for alarm {hay}')
            layer = a['label'].split(':')[0]
            layer = {'status': 'authenticity', 'label': 'support', 'revision': 'revision'}.get(layer, layer)
            kind = a['title'] if a['label'].startswith(('revision', 'status', 'label')) else a['label'].split(':', 1)[1]
            rec = {'unit_id': uid, 'paper': x['paper'], 'lang': x['lang'], 'layer': layer,
                   'kind': kind, 'alarm_label': a['label'], 'alarm_id': a['id'],
                   'severity': a['severity'],
                   'ref_ids': [r['id'] for r in x['refs']],
                   'anchor_text': sent[:80], 'unit': x['loc']['unit'], 'text_key': x['text_key'],
                   'verdict': s['verdict'], 'severity_ok': s['sev'], 'cause': s['cause'], 'subcause': s['sub'],
                   'evidence': s['evidence'], 'note': s['note']}
            recs.append(rec); n += 1
        done.add(uid)
with out.open('a') as fh:
    for rec in recs: fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
print('wrote', n, 'records; units labelled', len(done), '/', len(items))
