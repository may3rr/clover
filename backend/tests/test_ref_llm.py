"""Model-first reference structuring (grounded fields only) and the
gray-zone match adjudicator."""

import pytest

import citecheck.llm.client as llm
from citecheck.llm.client import LLMResult
from citecheck.refs import verify
from citecheck.refs.structure import _grounded, structure_references
from citecheck.schema import Reference

RAW = ("Patrick Lewis, Ethan Perez, and Douwe Kiela. 2020. Retrieval-augmented "
       "generation for knowledge-intensive NLP tasks. In Advances in Neural "
       "Information Processing Systems.")


def test_grounding_rejects_invented_fields():
    assert _grounded("year", 2020, RAW)
    assert not _grounded("year", 2021, RAW)
    assert _grounded("authors", ["Patrick Lewis"], RAW)
    assert not _grounded("authors", ["Jacob Devlin"], RAW)
    assert _grounded("title", "Retrieval-Augmented Generation for "
                     "Knowledge-Intensive NLP Tasks", RAW)
    assert not _grounded("title", "Dense passage retrieval", RAW)
    assert not _grounded("doi", "10.1000/xyz", RAW)


def _fake(monkeypatch, payload):
    async def fake(task, messages, schema, *, route="auto"):
        return LLMResult(value=schema.model_validate(payload), route="cloud")
    monkeypatch.setattr(llm, "chat_json", fake)


@pytest.mark.asyncio
async def test_structure_keeps_grounded_fields_only(monkeypatch):
    r = Reference(id="r1", raw=RAW, title="Patrick Lewis, Ethan Perez",
                  authors=[], year=None)
    _fake(monkeypatch, {"items": [{
        "i": 1,
        "title": "Retrieval-augmented generation for knowledge-intensive NLP tasks",
        "authors": ["Patrick Lewis", "Ethan Perez", "Douwe Kiela"],
        "year": 2020,
        "doi": "10.9999/made-up",
    }]})
    changed = await structure_references([r])
    assert changed == 1
    assert r.title.startswith("Retrieval-augmented")
    assert r.authors[0] == "Patrick Lewis" and r.year == 2020
    assert r.doi is None  # not in the entry -> rejected


@pytest.mark.asyncio
async def test_adjudicator_rescues_only_gray_candidates(monkeypatch):
    ref = Reference(id="r1", raw=RAW, title="Retrieval-augmented generation "
                    "for NLP", authors=["Patrick Lewis"], year=2020)
    near = {"title": "Retrieval-augmented generation for knowledge-intensive "
            "NLP tasks", "authors": ["Patrick Lewis"], "year": 2020}
    far = {"title": "Speech recognition with deep recurrent networks",
           "authors": ["Alex Graves"], "year": 2013}
    _fake(monkeypatch, {"match": 1, "reason": "标题省略了部分词"})
    hit = await verify._adjudicate(ref, [far, near])
    assert hit is not None and hit["title"] == near["title"]
    assert hit["adjudicated"]

    _fake(monkeypatch, {"match": None, "reason": "不确定"})
    assert await verify._adjudicate(ref, [near]) is None
    # nothing in the gray zone -> no model call needed, no rescue
    assert await verify._adjudicate(ref, [far]) is None
