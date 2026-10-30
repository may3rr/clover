"""逐项打印 parse_document 的结果，用来和 docx 肉眼内容对照（F33）。

用法：python dump_parse.py out/md_ieee.docx [更多 docx ...]
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from citecheck.parse import parse_document  # noqa: E402


def dump(path: str, n: int = 6) -> None:
    d = parse_document(path)
    paras = {p.id: p for p in d.paragraphs}
    print(f"\n######## {path}")
    print(f"title={d.document.title!r} style={d.document.citation_style} "
          f"managed_by={d.document.managed_by} words={d.document.word_count}")
    print(f"-- sections ({len(d.sections)})")
    for s in d.sections:
        n_p = sum(1 for p in d.paragraphs if p.section_id == s.id)
        print(f"   {s.id:4} {s.canonical:10} {n_p:3}p  {s.title[:70]!r}")
    print(f"-- references ({len(d.references)})")
    for r in d.references[:n]:
        print(f"   {r.id:4} label={r.label!r} year={r.year} "
              f"authors={r.authors[:2]} title={(r.title or '')[:60]!r}")
        print(f"        raw={r.raw[:110]!r}")
    print(f"-- markers ({len(d.markers)}) kinds={Counter(m.kind for m in d.markers)}")
    for m in d.markers[:n * 2]:
        print(f"   {m.id:4} {m.kind:12} {m.raw!r:42} -> {m.ref_ids}")
    unlinked = [m for m in d.markers if not m.ref_ids]
    print(f"   unlinked={len(unlinked)} {[m.raw for m in unlinked][:8]}")
    cited = {r for m in d.markers for r in m.ref_ids}
    print(f"   refs never cited={[r.id for r in d.references if r.id not in cited]}")
    tables = {p.cell.table for p in d.paragraphs if p.cell}
    imgs = sum(len(p.images) for p in d.paragraphs)
    caps = [p.text[:60] for p in d.paragraphs if p.caption]
    print(f"-- tables={len(tables)} images={imgs} captions={caps}")


for f in sys.argv[1:]:
    dump(f)
