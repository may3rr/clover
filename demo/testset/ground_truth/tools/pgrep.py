"""pgrep.py FILE PATTERN [ctx]: search PDF (or text) with whitespace removed, NFKC."""
import sys, re, unicodedata, fitz
f, pat = sys.argv[1], sys.argv[2]
ctx = int(sys.argv[3]) if len(sys.argv) > 3 else 80
n = lambda s: unicodedata.normalize('NFKC', s)
if f.endswith('.pdf'):
    doc = fitz.open(f); pages = [n(pg.get_text()) for pg in doc]
else:
    pages = [n(open(f).read())]
P = re.sub(r'\s+', '', n(pat))
hits = 0
for i, t in enumerate(pages):
    flat = re.sub(r'\s+', '', t)
    for m in re.finditer(re.escape(P), flat, flags=re.I):
        print(f"p{i+1}: …{flat[max(0,m.start()-ctx):m.end()+ctx]}…"); hits += 1
        if hits > 6: sys.exit()
if not hits: print('NO HIT')
