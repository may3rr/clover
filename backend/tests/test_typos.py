

def test_overreach_guards():
    from citecheck.lint.typos import _overreach
    # pure insertion after LaTeX dropped a \ref
    t = "Fig. (left) shows the behaviors."
    assert _overreach(t, t, "", "X ", 5, 5)
    # a letter inside a word is a slip, not an insertion
    t = "we recive data"
    assert not _overreach(t, t, "", "e", 6, 6)
    # case-only change in a lower-cased dataset sample
    t = "ground-truth: dani alves was not selected for the brazil squad ."
    s = t.index("brazil")
    assert _overreach(t, t, "brazil", "Brazil", s, s + 6)
    # case-only change in normal prose is kept (SquAD -> SQuAD)
    t = "Results on SquAD are shown in Table 2."
    s = t.index("SquAD")
    assert not _overreach(t, t, "SquAD", "SQuAD", s, s + 5)
    # an author's name used twice is not changed
    doc = "Rewon Child wrote it. Thanks to Rewon Child."
    assert _overreach(doc, doc, "Rewon", "Rezwon", 0, 5)
    # real-word slips in lowercase stay ('expect' used elsewhere)
    doc = "We expect gains. All layers expect the last one. We expect more."
    s = doc.index("expect the")
    assert not _overreach(doc, doc, "expect", "except", s, s + 6)
