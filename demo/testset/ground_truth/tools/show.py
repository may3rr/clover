import json, sys
p = json.load(open('/Users/jackielyu/Coding/tmall/demo/testset/ground_truth/pool/items.json'))
mode = sys.argv[1]; paper = sys.argv[2] if len(sys.argv) > 2 else None
for i, x in enumerate(p):
    if paper and x['paper'] != paper: continue
    if mode == 'typo':
        for t in x['typos']:
            src = t.get('source') or {}
            s = (src.get('text') or t.get('source_missing') or '').replace('\n', '⏎')
            d = t['docx']['text']; h = t['docx']['hl']
            print(f"{x['id']} [{x['stratum'][:12]}] 「{t['old']}」→「{t['new']}」 | {t['reason'][:80]}")
            print(f"   docx: …{d[max(0,h[0]-40):h[1]+40]}…")
            print(f"   src : {s[:220]}")
