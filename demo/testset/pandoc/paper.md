---
title: "Retrieval Signals for Citation Verification in Scientific Writing"
author:
  - Alex Chen
  - Jordan Lee
abstract: |
  We study whether retrieval signals help verify that cited papers support the claims attached to them. We combine dense retrieval with cross-encoder reranking and evaluate on a small benchmark of claim-citation pairs.
---

# Introduction

Large pretrained language models have changed how scientific text is processed [@vaswani2017attention; @devlin2019bert]. The Transformer architecture relies entirely on attention [@vaswani2017attention], and bidirectional pretraining improves many downstream tasks [@devlin2019bert]. Scaling model size further enables few-shot learning [@brown2020language].

Citation verification is a related but distinct problem. @wadden2020fact introduced SciFact, a dataset for verifying scientific claims against abstracts. Earlier work on citation function classification [@teufel2006automatic; @cohan2019structural] focused on why authors cite rather than whether the citation is accurate.

## Contributions

We make two contributions. First, we build a retrieval pipeline that pairs each claim with candidate evidence [@karpukhin2020dense]. Second, we show that reranking with a cross-encoder [@nogueira2019passage] improves precision [see @nogueira2019passage, p. 3].

# Related Work

## Dense retrieval

Dense passage retrieval [@karpukhin2020dense] encodes questions and passages with separate BERT encoders [@devlin2019bert]. Sentence embeddings trained with siamese networks [@reimers2019sentence] are a cheaper alternative.

## Scientific document understanding

SciBERT [@beltagy2019scibert] adapts BERT to scientific text. S2ORC [@lo2020s2orc] provides a large corpus of full-text papers with resolved citation links.

# Method

Given a claim $c$ and a cited paper $d$, we retrieve the top-$k$ passages and score each pair. Table 1 lists the components.

| Component | Model | Parameters |
|-----------|-------|-----------:|
| Retriever | DPR [@karpukhin2020dense] | 110M |
| Reranker  | monoBERT [@nogueira2019passage] | 340M |
| Judge     | NLI classifier | 355M |

: Pipeline components and their sizes. {#tbl:components}

![Overview of the verification pipeline.](figure1.png){#fig:overview width=60%}

Figure 1 shows the overall pipeline.

# Experiments

We evaluate on SciFact [@wadden2020fact] and report label accuracy. Following @lo2020s2orc we restrict the corpus to papers with full text.

## Results

Reranking improves label accuracy from 0.71 to 0.78. The gain is consistent with prior findings on passage reranking [@nogueira2019passage; @karpukhin2020dense; @reimers2019sentence].

# Conclusion

Retrieval signals help citation verification, but the remaining errors come from claims that paraphrase the cited result loosely.

# References {-}

::: {#refs}
:::
