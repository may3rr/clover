# 演示材料备忘

收集可以放进答辩 PPT 的事实与数字，每条注明出处。

## 1. 引用是否准确，人也很难判得一致

Sarol、Schneider 与 Kilicoglu 在 2024 年发表的生物医学引用准确性研究中，对 100 篇高被引文献的 3063 条引用逐条人工标注。两位标注员对引用是否准确的一致性，Cohen's κ 只有 0.18 到 0.31；对引用语境的一致性达到 0.96。也就是说，找出哪句话在引用哪篇文献，人可以做得很一致；判断被引文献是否真的支持这句话，人和人之间也经常判得不一样。

可用于说明：

- 支持度判断没有唯一正确答案，评测结果要放在这个背景下看。
- Clover 对每条判断都给出被引文献的原文证据，最终由作者决定，这是产品设计上的回应。

出处：Sarol M J, Schneider J, Kilicoglu H. Assessing citation integrity in biomedical publications: corpus annotation and NLP models. Bioinformatics, 2024. https://pmc.ncbi.nlm.nih.gov/articles/PMC11231046/

## 2. 同一研究中的相关数字

- 3063 条引用中约 39% 存在准确性问题，其中 18% 属于严重问题，例如矛盾、无依据或与被引文献无关。
- GPT-4 识别准确引用的 F1 为 0.80，识别不准确引用的 F1 只有 0.09。
- 当时最好的模型 micro-F1 为 0.59；直接给出人工标注的关键原文后升到 0.75，找对原文是主要瓶颈之一。
- 检索前 20 句时，关键原文的召回率约为 0.55。

出处同上。

## 3. Clover 在公开人工标注数据集上的表现

在 Citation-Integrity 测试集 606 条人工标注的真实引文上，只用 qwen3.8-flash 的 Clover 流程：标准准确率 0.62，与原论文报告的 GPT-4 的 0.65 相当；识别不准确引用的 F1 为 0.30，GPT-4 为 0.09；报出的问题中约 73% 确实有问题。

出处：本仓库 `demo/testset/item_bench/results.md` 第 15 节。

