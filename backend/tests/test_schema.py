"""Round-trip serialization of a fully populated Report (AGENTS §5.1)."""

from citecheck.schema import (
    Anchor,
    CitationMarker,
    Claim,
    Document,
    Finding,
    LayerStatus,
    Paragraph,
    RefCheck,
    Reference,
    Report,
    Revision,
    Section,
    SupportCheck,
)


def _full_report() -> Report:
    return Report(
        document=Document(
            title="A Study of Citation Practices",
            filename="paper.docx",
            citation_style="numeric",
            managed_by="zotero",
            word_count=4200,
        ),
        sections=[Section(id="s1", title="1 Introduction", canonical="intro")],
        paragraphs=[
            Paragraph(
                id="p0", section_id="s1", text="Transformers work well [1].", char_offset=0
            )
        ],
        markers=[
            CitationMarker(
                id="m0", paragraph_id="p0", start=23, end=26, raw="[1]", ref_ids=["r1"]
            )
        ],
        references=[
            Reference(
                id="r1",
                raw="[1] Vaswani A, et al. Attention is all you need. NeurIPS, 2017.",
                title="Attention is all you need",
                authors=["Vaswani A"],
                year=2017,
                venue="NeurIPS",
                doi="10.48550/arXiv.1706.03762",
                lang="en",
                paragraph_id="p9",
                label="1",
            )
        ],
        ref_checks=[
            RefCheck(ref_id="r1", status="verified", matched={"title": "Attention is all you need"})
        ],
        claims=[
            Claim(
                id="c0", paragraph_id="p0", start=0, end=23,
                text="Transformers work well", marker_ids=["m0"],
            )
        ],
        support_checks=[
            SupportCheck(
                claim_id="c0",
                ref_id="r1",
                label="supported",
                evidence="the Transformer",
                source_kind="abstract",
                rationale="原文明确支持该论断",
                source_title="Attention is all you need",
                source_excerpt="We propose the Transformer, a model architecture.",
                evidence_span=(12, 27),
            )
        ],
        distribution={"intro": 0.4, "related": 0.6},
        findings=[
            Finding(
                id="f0",
                layer="authenticity",
                severity="high",
                anchor=Anchor(paragraph_id="p9", start=0, end=10),
                title="文献信息不符",
                detail="年份与数据库记录不一致",
                refs=["r1"],
            )
        ],
        revisions=[
            Revision(
                id="v0",
                kind="marker_renumber",
                anchor=Anchor(paragraph_id="p0", start=23, end=26),
                old="[1]",
                new="[3]",
                reason="参考文献重排后编号变化",
            ),
            Revision(
                id="v1",
                kind="ref_reorder",
                anchor=Anchor(paragraph_id="p9", start=0, end=10),
                old="...",
                new="...",
                reason="按首次引用顺序重排",
                move_after="p8",
            ),
        ],
    )


def test_report_round_trip():
    report = _full_report()
    restored = Report.model_validate_json(report.model_dump_json())
    assert restored == report


def test_report_dump_dict_round_trip():
    report = _full_report()
    restored = Report.model_validate(report.model_dump())
    assert restored == report


def test_report_meta_defaults_and_layers():
    report = _full_report()
    assert report.meta.llm_calls.local == 0
    assert report.meta.llm_calls.cloud == 0
    report.meta.layers["authenticity"] = LayerStatus(status="done", findings=3)
    data = report.model_dump_json()
    assert '"findings":3' in data
    assert Report.model_validate_json(data).meta.layers["authenticity"].status == "done"


def test_json_schema_generated():
    schema = Report.model_json_schema()
    assert "CitationMarker" in schema["$defs"]
    assert "Anchor" in schema["$defs"]
