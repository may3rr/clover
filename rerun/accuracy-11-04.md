# 准确度重跑记录 11-04

运行时间 2026-11-04 11:38 至 11:42，分支 `finals-dev`，改动未提交。对照起点为 `PRE_HACKATHON_BASELINE.md`（标签 `v0.9-pre-hackathon`）。配置与基线相同：所有对话任务 qwen3.8-flash，温度 0，向量与重排经硅基流动，沿用主缓存库，只有受改动影响的调用重新请求模型，因此 20 份报告约 4 分钟跑完。

## 1. 本轮改动

| 编号 | 改动 | 位置 | 对应问题 |
| --- | --- | --- | --- |
| A1 | 同一句只引一篇文献时，即使标记出现多次，作者归属照常检查 | `lint/attribution.py` | 痛点 1，英文演示稿 author_swap 漏检 |
| A2 | 第一轮判为支持时，论断中带单位的数字在原文片段中找不到而片段有同单位的其他数字，或理由写明不一致，送复核并附一句提示，结论仍由模型给出 | 新增 `support/consistency.py`，接入 `support/layer.py` `_cascade`，`support/judge.py` 增加 `hint` | 痛点 2，number_bn 漏检 |
| A3 | 论断紧跟自身引用标记、其后接 which、who、whose 或"其、该方法"等从句时，把从句并入论断 | `support/claims.py` `_extend_relative_clause` | 痛点 3，overclaim 漏检 |
| A4 | 引用堆砌按引用簇计数，只有相邻标记合并，逐项列举各带引用的句子不报；与基准对比的逐句统计不变 | `distribution/layer.py` `_clusters` | ground truth 误报第 1 类 |
| A5 | 错别字三条守卫：不凭空补词，整段小写的数据集样例不改大小写，作者多次使用的非小写词不改成全文未出现的词 | `lint/typos.py` `_overreach` | ground truth 误报第 4 类 |
| E1 | 评测脚本支持 `CLOVER_REPORTS`、`CLOVER_RESULTS` 指定目录，默认不变 | `run_all.sh`、`run_en.sh`、`evaluate_corpus.py` | 重跑不覆盖基线报告 |

A4、A5 的每条规则都先用 `demo/testset/ground_truth/labels.jsonl` 逐条核对过：A4 保留全部注入堆砌，A5 去掉的 19 条修订全部是人工标为误报的条目，注入错别字无一受影响。

测试：后端 pytest 507 通过、3 跳过，新增 15 条。

## 2. 注入实验

报告在 `demo/testset/reports_r1104/`，评测结果在 `demo/testset/results_r1104/`。

| 语料 | 版本 | 查全率 | 查准率（宽） | 查准率（严） | 干净稿既有报警单元 | 新增误报 | 支持度确定判断覆盖 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 中文 5 篇 | 基线 | 0.977 | 0.956 | 0.133 | 279 | 2 | 71.7% |
| 中文 5 篇 | 本轮 | 0.977 | 0.956 | **0.150** | **242** | 2 | 71.7% |
| 英文 5 篇 | 基线 | 0.905 | 0.950 | 0.168 | 186 | 2 | 85.1% |
| 英文 5 篇 | 本轮 | 0.905 | **1.000** | **0.217** | **137** | **0** | 84.5% |

- 干净稿报警单元合计从 465 降到 379，查全率不变。
- 张冠李戴检出仍为中文 9/10、英文 6/10。语料中的张冠李戴漏检主要是一句多引和只有摘要两类，本轮没有处理。
- 中文干净稿的错别字修订只从 110 降到 108，A5 只作用于拉丁文字，中文错别字误报主要是转换痕迹。

干净稿既有报警按类型的变化：

| 类型 | 中文基线 | 中文本轮 | 英文基线 | 英文本轮 |
| --- | --- | --- | --- | --- |
| 引用堆砌 | 52 | 7 | 63 | 15 |
| 错别字修订 | 110 | 108 | 64 | 49 |
| 支持度：不支持 | 50 | 53 | 42 | 48 |
| unsupported 标签 | 63 | 65 | 43 | 47 |
| 其余类型 | 基本不变 | | 基本不变 | |

## 3. 对照人工 ground truth

命令：`python demo/testset/ground_truth/score.py --reports demo/testset/reports_r1104`。只统计已标注的报警，新出现、尚未标注的报警单独列出。

| 语言 | 口径 | 基线严 | 本轮严 | 基线宽 | 本轮宽 |
| --- | --- | --- | --- | --- | --- |
| 中文 | 既有报警单元 | 0.262 | **0.309** | 0.358 | **0.424** |
| 中文 | 全语料 | 0.358 | **0.404** | 0.441 | **0.498** |
| 英文 | 既有报警单元 | 0.172 | **0.260** | 0.226 | **0.341** |
| 英文 | 全语料 | 0.310 | **0.400** | 0.354 | **0.457** |

- 不再报出的已标注报警：中文 50 条、英文 74 条，全部是人工标为误报的条目，没有丢掉任何真问题。
- 剩余误报原因，中文：转换痕迹 70、灰色文献 17、支持度判断错误 14、解析错误 13、错别字过度修改 12；英文：支持度判断错误 36、错别字过度修改 17、检索未取到支持段落 13、引用堆砌 9。
- 未标注的新报警：中文 8 条，英文 20 条。

### 3.1 新增报警中 A2 带来的部分

把基线中判为支持、本轮改判为不支持的配对逐一追溯，8 处中 6 处经过 A2 送复核：

| 稿件 | 文献 | 论断 | 定性 |
| --- | --- | --- | --- |
| guyingjie_mrc | [10] | 相比基线 63.33% 提升了 0.42% | 误报。原文 63.75 减 63.33 正好是 0.42，复核模型认为原文没有直接写出这个差值 |
| en_resnet | r7 | RoI pooling is performed before conv5_1 | 误报。这是 ResNet 作者自己的做法 |
| en_resnet | r42 | fewer parameters than FitNet and Highway，6.43% | 误报。6.43% 是作者自己的结果 |
| en_gpt3 | r64 | still 4.1% lower than the fine-tuned SOTA | 大概率误报。差值由作者计算 |
| en_gpt3 | r121 | task-specific approaches to distillation | 待标注，理由触发 |
| zhaoyangyang_tod | r161 | 基于检索的模型无法处理过长的语句 | 待标注，理由触发 |

另外 2 处（en_gpt3 r116、en_t5 r3）没有经过 A2，属于检索片段的波动。

A2 在演示稿上抓到了 number_bn 和 overclaim，在干净稿上带来的主要是这一类误报：论断里的数字是作者自己的结果或由原文数字计算得出，复核提示把模型推向了不支持。A2 需要收紧，见第 5 节。

## 4. 演示稿

| 演示稿 | 基线 | 本轮 | 报告 |
| --- | --- | --- | --- |
| 英文 ResNet LaTeX | 12/16 | **16/16** | `demo/final/runs/en_v2_r1104.json` |
| 中文罗会兰 docx | 17/17 | 未重跑 | |

英文演示稿新检出的四处：author_swap 由 A1 检出，number_bn 由 A2 检出，overclaim 由 A3 检出，misattr_dataset 来自检索片段的变化，不是本轮规则的作用。注入以外的报警从 33 条增加到 40 条，新增高严重度中 1 条来自 A2（r7），3 条来自 Venables 与 Ripley 的统计教科书这次只取到版权页作为摘要，其余为检索片段波动。

## 5. 下一步

1. 收紧 A2：论断数字能由片段中两个同单位数字相减或相除得到时不送复核；数字出现在作者自述句中时不送复核；复核提示改为只陈述差异，不暗示结论。改完用本轮 6 处和演示稿两处做回归。
2. 原文片段只有版权页、封面或出版信息时按未取得原文处理。
3. 支持度按引用标记切分论断，一句多引时只判该标记负责的片段，对应 ground truth 误报第 3 类，也是张冠李戴漏检的主要来源。
4. 补标本轮 28 条未标注报警，运行 `score.py --add-keys` 更新报警键。
5. 中文转换痕迹 70 条属于测试集问题，可以用出版社全文重建中文测试稿。

## 6. 复现

```bash
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate claude
export CLOVER_REPORTS=demo/testset/reports_r1104 CLOVER_RESULTS=demo/testset/results_r1104
bash demo/testset/run_all.sh && bash demo/testset/run_en.sh
python demo/testset/evaluate_corpus.py && python demo/testset/evaluate_corpus.py en
python demo/testset/ground_truth/score.py --reports demo/testset/reports_r1104
python demo/run_pipeline.py "demo/final/英文演示稿/deep_residual_learning.zip" demo/final/runs/en_v2_r1104.json "demo/final/英文演示稿/ref"
python demo/final/check_final.py demo/final/runs/en_v2_r1104.json demo/final/injections_en.json
```
