"""Regressions from the long EMNLP-style fixtures (demo/long): ACL-format
references, full-name surnames, table cells vs headings, unnumbered
standalone headings."""

from lxml import etree

from citecheck.parse import docx_xml as dx
from citecheck.parse.headings import heading_level
from citecheck.parse.links import _ref_first_surname
from citecheck.refs.structure import parse_reference
from citecheck.schema import Reference



def _p(in_table: bool = False):
    p = etree.Element(dx.qn("p"))
    if not in_table:
        return p
    tc = etree.Element(dx.qn("tc"))
    tc.append(p)
    return p


def test_acl_reference_fields():
    r = parse_reference(
        "Patrick Lewis, Ethan Perez, Aleksandra Piktus, and Douwe Kiela. 2020. "
        "Retrieval-augmented generation for knowledge-intensive NLP tasks. In "
        "Advances in Neural Information Processing Systems, pages 9459–9474.")
    assert r["authors"][0] == "Patrick Lewis" and r["authors"][-1] == "Douwe Kiela"
    assert r["year"] == 2020
    assert r["title"].startswith("Retrieval-augmented generation")
    assert r["venue"] == "Advances in Neural Information Processing Systems"


def test_acl_title_ending_in_question_mark():
    r = parse_reference(
        "Emily M. Bender, Timnit Gebru, and Angelina McMillan-Major. 2021. On "
        "the dangers of stochastic parrots: Can language models be too big? In "
        "Proceedings of the 2021 ACM Conference on Fairness, Accountability, "
        "and Transparency, pages 610–623.")
    assert r["authors"][0] == "Emily M. Bender"
    assert r["title"].endswith("too big?")
    assert r["venue"].startswith("Proceedings of the 2021 ACM")


def test_event_and_doi_years_are_not_publication_years():
    r = parse_reference(
        "Ivan Stelmakh, Yi Luan, Bhuwan Dhingra, and Ming-Wei Chang. ASQA: "
        "Factoid questions meet long-form answers. In Proceedings of the 2022 "
        "Conference on Empirical Methods in Natural Language Processing. "
        "https://doi.org/10.18653/v1/2022.emnlp-main.566")
    assert r["year"] is None
    assert r["authors"][0] == "Ivan Stelmakh"


def test_first_surname_handles_name_orders():
    def s(a):
        return _ref_first_surname(Reference(id="r", raw="", authors=[a]))
    assert s("Devlin, J.") == "Devlin"
    assert s("Devlin J") == "Devlin"
    assert s("Jacob Devlin") == "Devlin"
    assert s("Daniel K. Osei") == "Osei"
    assert s("Aaron van den Oord") == "van den Oord"


def test_numbers_are_not_headings():
    assert heading_level(_p(), "40.1", {}) is None
    assert heading_level(_p(), "12 0.35", {}) is None
    assert heading_level(_p(in_table=True), "3 Method", {}) is None
    assert heading_level(_p(), "3.2 Training Objective", {}) == 2


def test_standalone_unnumbered_headings():
    for t in ["Abstract", "Limitations", "Ethics Statement", "References",
              "Acknowledgments:"]:
        assert heading_level(_p(), t, {}) == 1, t
    assert heading_level(_p(), "Results are mixed.", {}) is None
