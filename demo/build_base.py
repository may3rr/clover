"""T11a: build the clean demo paper -> demo/base_paper.docx.

A ~3k-word English NLP paper with a Word Title style, Heading 1
sections, plain-text numeric [n] markers and 24 real references. Every
citing sentence is a faithful paraphrase of the cited paper's abstract
(or a general background statement), so the clean run should produce no
high-severity findings.

Run:  python demo/build_base.py
"""

from __future__ import annotations

import random
from pathlib import Path

from docx import Document

HERE = Path(__file__).resolve().parent

random.seed(42)

# ------------------------------------------------------------- references
# (label, raw string) — real papers, mostly with arXiv versions so
# abstracts/fulltext are retrievable.
REFERENCES = [
    "Vaswani A, Shazeer N, Parmar N, et al. Attention is all you need. "
    "Advances in Neural Information Processing Systems. 2017;30:5998-6008.",
    "Devlin J, Chang M-W, Lee K, Toutanova K. BERT: Pre-training of deep "
    "bidirectional transformers for language understanding. Proceedings "
    "of NAACL-HLT. 2019:4171-4186. doi:10.18653/v1/N19-1423.",
    "Brown TB, Mann B, Ryder N, et al. Language models are few-shot "
    "learners. Advances in Neural Information Processing Systems. "
    "2020;33:1877-1901.",
    "Raffel C, Shazeer N, Roberts A, et al. Exploring the limits of "
    "transfer learning with a unified text-to-text transformer. Journal "
    "of Machine Learning Research. 2020;21(140):1-67.",
    "Touvron H, Martin L, Stone K, et al. Llama 2: Open foundation and "
    "fine-tuned chat models. arXiv preprint arXiv:2307.09288. 2023.",
    "Lewis P, Perez E, Piktus A, et al. Retrieval-augmented generation "
    "for knowledge-intensive NLP tasks. Advances in Neural Information "
    "Processing Systems. 2020;33:9459-9474.",
    "Guu K, Lee K, Tung Z, Pasupat P, Chang M-W. REALM: "
    "Retrieval-augmented language model pre-training. International "
    "Conference on Machine Learning. 2020:3929-3938.",
    "Karpukhin V, Oguz B, Min S, et al. Dense passage retrieval for "
    "open-domain question answering. Proceedings of EMNLP. "
    "2020:6769-6781.",
    "Izacard G, Grave E. Leveraging passage retrieval with generative "
    "models for open domain question answering. Proceedings of EACL. "
    "2021:874-880.",
    "Izacard G, Lewis P, Lomeli M, et al. Atlas: Few-shot learning with "
    "retrieval augmented language models. Journal of Machine Learning "
    "Research. 2023;24(251):1-43.",
    "Khattab O, Zaharia M. ColBERT: Efficient and effective passage "
    "search via contextualized late interaction over BERT. Proceedings "
    "of SIGIR. 2020:39-48.",
    "Santhanam K, Khattab O, Saad-Falcon J, Potts C, Zaharia M. "
    "ColBERTv2: Effective and efficient retrieval via lightweight late "
    "interaction. Proceedings of NAACL. 2022:3715-3734.",
    "Robertson S, Zaragoza H. The probabilistic relevance framework: "
    "BM25 and beyond. Foundations and Trends in Information Retrieval. "
    "2009;3(4):333-389. doi:10.1561/1500000019.",
    "Shuster K, Poff S, Chen M, Kiela D, Weston J. Retrieval "
    "augmentation reduces hallucination in conversation. Findings of "
    "EMNLP. 2021:3784-3803.",
    "Menick J, Trebacz M, Mikulik V, et al. Teaching language models to "
    "support answers with verified quotes. arXiv preprint "
    "arXiv:2203.11147. 2022.",
    "Asai A, Wu Z, Wang Y, Sil A, Hajishirzi H. Self-RAG: Learning to "
    "retrieve, generate, and critique through self-reflection. "
    "International Conference on Learning Representations. 2024.",
    "Jiang Z, Xu FF, Gao L, et al. Active retrieval augmented "
    "generation. Proceedings of EMNLP. 2023:7969-7992.",
    "Ji Z, Lee N, Frieske R, et al. Survey of hallucination in natural "
    "language generation. ACM Computing Surveys. 2023;55(12):1-38.",
    "Gao T, Yen H, Yu J, Chen D. Enabling large language models to "
    "generate text with citations. Proceedings of EMNLP. "
    "2023:6465-6488.",
    "Min S, Krishna K, Lyu X, et al. FActScore: Fine-grained atomic "
    "evaluation of factual precision in long form text generation. "
    "Proceedings of EMNLP. 2023:12076-12100.",
    "Manakul P, Liusie A, Gales MJF. SelfCheckGPT: Zero-resource "
    "black-box hallucination detection for generative large language "
    "models. Proceedings of EMNLP. 2023:15452-15464.",
    "Gao L, Dai Z, Pasupat P, et al. RARR: Researching and revising what "
    "language models say, using language models. Proceedings of ACL. "
    "2023:16477-16508.",
    "Bohnet B, Liu VQ, Kwiatkowski T, Alberti C. Attributed question "
    "answering: Evaluation and modeling for attributed large language "
    "models. arXiv preprint arXiv:2212.08037. 2022.",
    "Rashkin H, Nikolaev V, Lamm M, et al. Measuring attribution in "
    "natural language generation models. Computational Linguistics. "
    "2023;49(4):777-840.",
]

TITLE = ("Grounded but Wrong: Measuring Citation Hallucination in "
         "Retrieval-Augmented Generation")

# ------------------------------------------------------------- body text
# Each paragraph is a list of strings; "[n]" inside a string is a plain
# numeric marker. Keep every cited claim a faithful paraphrase of the
# cited paper's abstract.
ABSTRACT = (
    "Retrieval-augmented generation grounds a language model in external "
    "documents, but the citation that accompanies a generated statement "
    "can still be wrong even when the statement itself is sensible. We "
    "study this citation hallucination directly: we check, for a corpus "
    "of machine-generated answers, whether each cited source actually "
    "supports the claim it is attached to. We propose a verification "
    "protocol that requires the supporting evidence to be located "
    "verbatim in the cited document before a claim is counted as "
    "supported, and we report how often plausible-looking citations "
    "fail this test. Our results suggest that citation accuracy is a "
    "distinct failure axis that standard factuality metrics do not "
    "capture, and that evidence-grounded checking catches errors that "
    "surface-level string matching misses."
)

SECTIONS = [
    ("1 Introduction", [
        "Large language models produce fluent text at scale, and "
        "attention-based architectures have been the foundation of this "
        "progress since the Transformer replaced recurrence with "
        "attention mechanisms alone [1]. Pre-trained encoders that "
        "condition jointly on left and right context, such as BERT, "
        "later showed that deep bidirectional representations transfer "
        "across tasks [2], and scaling few-shot learners demonstrated "
        "that large models can perform tasks from a handful of "
        "in-context examples [3]. General-purpose transfer frameworks "
        "such as the text-to-text recipe of T5 then showed that a "
        "single encoder-decoder trained on a unified objective reaches "
        "strong results across many benchmarks [4], and open "
        "foundations such as Llama 2 have since made large instruction "
        "models broadly available to the research community [5].",
        "Retrieval-augmented generation combines this parametric memory "
        "with a non-parametric corpus: Lewis et al. show that "
        "retrieval-augmented models for knowledge-intensive NLP tasks "
        "generate more specific, diverse and factual language than a "
        "comparable parametric-only baseline [6]. REALM takes the same "
        "idea into pre-training, learning a neural knowledge retriever "
        "jointly with the language model itself [7]. These systems lean "
        "on a retriever whose quality was established by dense passage "
        "retrieval, which showed that a dual-encoder can outperform "
        "strong lexical baselines on open-domain question answering "
        "[8].",
        "However, grounding is not the same as attribution. A generated "
        "sentence may carry a citation marker that points to a real "
        "paper while the paper says nothing about the claim. We call "
        "this failure citation hallucination: the reference exists, the "
        "claim is plausible, but the link between them is fabricated. "
        "The phenomenon sits inside the broader taxonomy of "
        "hallucination surveyed for natural language generation, but "
        "it has received less direct measurement than outright factual "
        "errors [18]. This paper operationalizes a conservative check "
        "for it: a claim is supported only when the supporting evidence "
        "can be located verbatim inside the cited source.",
    ]),
    ("2 Related Work", [
        "Retrieval pipelines for open-domain tasks have moved steadily "
        "from sparse to dense representations. Dense passage retrieval "
        "showed that a simple dual-encoder can outperform BM25 on "
        "open-domain question answering benchmarks [8], while the "
        "probabilistic relevance framework remains the reference "
        "baseline for lexical matching [13]. Late-interaction models "
        "keep token-level representations and score them cheaply: "
        "ColBERT computes fine-grained contextual similarity over BERT "
        "representations [11], and ColBERTv2 makes the same interaction "
        "lighter with denoised supervision and residual compression "
        "[12]. On the generative side, fusion-in-decoder reads each "
        "retrieved passage independently and fuses them in the decoder "
        "[9], Atlas shows that retrieval-augmented models can learn "
        "from very few examples [10], and unified text-to-text "
        "frameworks treat every task as generation [4].",
        "Hallucination itself has been surveyed as a broad phenomenon "
        "in natural language generation [18]. For dialogue "
        "specifically, retrieval augmentation has been reported to "
        "reduce hallucination while keeping responses engaging [14]. "
        "Several systems now try to make generation self-verifying: "
        "Self-RAG trains a model to retrieve, generate and critique its "
        "own output through reflection tokens [16]; FLARE-style active "
        "retrieval decides during generation when to retrieve and what "
        "query to issue [17]; and GopherCite-style models are taught to "
        "support their answers with verified quotes [15]. Open "
        "foundation models such as Llama 2 make these techniques widely "
        "reproducible [5].",
        "Evaluation has developed in parallel. ALCE provides a "
        "benchmark for enabling and measuring citation in long-form "
        "model output [19]. FActScore decomposes long generations into "
        "atomic facts to score factual precision [20]. SelfCheckGPT "
        "detects hallucination in a zero-resource black-box setting by "
        "checking consistency across sampled responses [21]. RARR "
        "retrofits attribution onto existing models by researching and "
        "revising their outputs against retrieved evidence [22]. The "
        "AIS framework defines what it means for a statement to be "
        "attributable to identified sources [24], and attributed "
        "question answering evaluates whether model answers can be "
        "justified by a source document [23].",
    ]),
    ("3 Method", [
        "We treat each machine-generated sentence that carries one or "
        "more numeric citation markers as a claim-to-verify. For each "
        "claim and each cited reference we assemble the strongest "
        "retrievable source text: the abstract first, then open-access "
        "full text when it is available, using the dense-retrieval "
        "excerpts that best match the claim [8].",
        "A claim is judged supported only when the model that checks it "
        "returns an evidence span that can be located verbatim in the "
        "source text. This is deliberately stricter than the consistency "
        "probes used by black-box hallucination detectors [21]: the "
        "evidence must exist as a contiguous span, otherwise the check "
        "is inconclusive rather than silently failed. When no source "
        "text can be retrieved the pair is marked undetermined instead "
        "of unsupported, following the conservative attribution stance "
        "of AIS [24].",
        "The verifier itself is a language model prompted with the "
        "claim, the title of the cited work, and the assembled excerpt, "
        "mirroring the evaluation setup of ALCE [19]. Because model "
        "judgements are fallible, every verdict carries the verbatim "
        "evidence the model returned, and a post-check rejects verdicts "
        "whose evidence cannot be found in the excerpt. In that design "
        "the protocol inherits the fine-grained spirit of atomic-fact "
        "evaluation [20] while keeping the check reproducible.",
        "We apply the protocol to answers produced with "
        "retrieval-augmented generation in the style of RAG [6], where "
        "every paragraph is generated jointly with its citations. Each "
        "answer paragraph typically cites between one and four "
        "references, so the corpus exercises both single-source claims "
        "and claims that span several retrieved documents.",
    ]),
    ("4 Experiments", [
        "We generated answers for 120 questions drawn from "
        "knowledge-intensive domains, each with three to six cited "
        "references. Every citing sentence was paired with the source "
        "text assembled as described above, and each pair was judged "
        "supported, partially supported, unsupported or undetermined. "
        "The retrieval component itself was standard: a dense "
        "dual-encoder retriever over Wikipedia-style passages [8], with "
        "no task-specific tuning.",
        "Across the corpus, most citations did carry real support, "
        "which is consistent with reports that retrieval augmentation "
        "reduces hallucination in generated text [14]. The failures "
        "that remained were concentrated in two patterns: a claim that "
        "merged facts from two sources citing only one, and a claim "
        "that overstated what the source reported, which the "
        "fine-grained decomposition of FActScore also flags as a "
        "precision problem [20].",
        "Post-hoc revision in the style of RARR recovered a large share "
        "of the partially supported pairs, because the needed evidence "
        "usually existed elsewhere in the same document [22]. The "
        "remaining unsupported pairs were genuine citation "
        "hallucinations: real references attached to claims the "
        "references do not make. We also observed that pairs scored "
        "against full text were resolved more often than pairs scored "
        "against abstracts alone, consistent with the richer evidence "
        "available when open-access text is retrievable [19].",
        "Ablating the verbatim-evidence rule confirms its necessity: "
        "without it, the verifier returns plausible verdicts whose "
        "quoted evidence does not appear in the source at all, an "
        "error class that consistency sampling alone does not reveal "
        "[21]. Requiring a located span converts that silent failure "
        "into an explicit undetermined label.",
    ]),
    ("5 Discussion", [
        "Three observations stand out. First, citation correctness is "
        "not a side effect of answer quality; fluent, correct answers "
        "still carried unsupported citations, echoing the distinction "
        "the attributed-question-answering line draws between being "
        "right and being attributable [23]. Second, verbatim evidence "
        "localization is the difference between checking and guessing: "
        "when the evidence cannot be located, reporting the pair as "
        "undetermined is more honest than either verdict. Third, the "
        "active-retrieval designs that decide when to fetch evidence "
        "[17] may reduce hallucination upstream, but they do not "
        "remove the need for downstream verification.",
        "Our protocol has clear limits. It cannot verify paywalled "
        "sources, it inherits the blind spots of dense retrieval when "
        "the relevant passage is missed [8], and a citation that is "
        "technically supported may still mislead a reader about the "
        "strength of the claim. The framework also assumes numeric "
        "marker citations in the author-date style studied by the "
        "attribution benchmarks we reuse [19]; linking prose citations "
        "to bibliography entries is itself a parsing problem we leave "
        "to the surrounding toolchain. We see the protocol as a floor "
        "for citation quality rather than a ceiling.",
    ]),
    ("6 Conclusion", [
        "We proposed a conservative protocol for detecting citation "
        "hallucination in retrieval-augmented generation: a claim is "
        "supported only when its evidence can be located verbatim in "
        "the cited source. Applied to a corpus of machine-generated "
        "answers, the check isolates a failure mode that neither "
        "automatic factuality metrics nor retrieval quality alone "
        "captures. Future work includes extending the check to sources "
        "without open text and studying whether citation-aware "
        "decoding can prevent the failure rather than merely detect "
        "it.",
    ]),
]


def split_runs(text: str) -> list[str]:
    """Split a string into 2-4 plausible Word runs (marker text can be
    split too — parse layer must tolerate it)."""
    if len(text) < 40 or random.random() < 0.4:
        return [text]
    n = random.choice([2, 2, 3])
    cuts = sorted(random.sample(range(8, len(text) - 8), n - 1))
    parts, prev = [], 0
    for c in cuts:
        parts.append(text[prev:c])
        prev = c
    parts.append(text[prev:])
    return parts


def add_para(doc, text: str, style: str | None = None):
    p = doc.add_paragraph(style=style)
    for piece in split_runs(text):
        p.add_run(piece)
    return p


def main() -> Path:
    doc = Document()
    doc.add_paragraph(TITLE, style="Title")
    doc.add_paragraph("Abstract", style="Heading 1")
    add_para(doc, ABSTRACT)
    for heading, paras in SECTIONS:
        doc.add_paragraph(heading, style="Heading 1")
        for para in paras:
            add_para(doc, para)
    doc.add_paragraph("References", style="Heading 1")
    for i, raw in enumerate(REFERENCES, 1):
        doc.add_paragraph(f"[{i}] {raw}")
    out = HERE / "base_paper.docx"
    doc.save(out)

    words = sum(
        len(p.split()) for _h, paras in SECTIONS for p in paras
    ) + len(ABSTRACT.split())
    print(f"wrote {out}  (~{words} words, {len(REFERENCES)} refs)")
    return out


if __name__ == "__main__":
    main()
