# Clover 决赛前基线（v0.9-pre-hackathon）

定格时间 2026-11-01。代码为 master 合入 `f36-accuracy-venue-rebench` 之后的版本（合并提交 `e3ece74`，标签 `v0.9-pre-hackathon`）。本文件是杭州 48 小时决赛的起点记录，现场每项改进都与这里的数字对照。

## 0. 基线条件

| 项 | 取值 |
| --- | --- |
| 自动化测试 | 后端 pytest 482 通过、3 跳过；前端 vitest 72 通过；typecheck、lint:design 通过 |
| 评测配置（开发机 `backend/config.toml`） | 所有对话任务 qwen3.8-flash，温度 0；向量 Qwen3-Embedding-0.6B、重排 Qwen3-Reranker-0.6B，均经硅基流动 |
| 产品默认配置（`config.example.toml`） | judge、typo qwen3.8-flash；review qwen3.8-max；extract、structure、function qwen3.7-flash；向量 text-embedding-v4、重排 qwen3-rerank，均经百炼。准确率没有在这套配置下完整跑过 |
| 缓存 | 注入实验沿用主缓存库，模型结论命中缓存；冷启动计时用全新空缓存库 |

本次基线过程中修掉的两处评测脚本问题：

1. `demo/testset/run_all.sh`、`run_en.sh` 原来把 `get_key.py` 读出的 **DeepSeek 密钥**写进 `DASHSCOPE_API_KEY`。10 月 24 日英文结果和 10 月 29 日之前的部分中文结果实际由 deepseek-flash 判断，不符合"全程使用 Qwen"。两个脚本已改为从 `backend/.env` 读百炼密钥，本文件所有数字都是 qwen3.8-flash 跑出的，报告 `meta.token_usage` 里只有这一个模型。
2. 英文语料原来没有文献文件夹。本次用 `item_bench/fetch_refs.py` 下载开放获取 PDF（arXiv 编号、OA 链接，新增按标题检索 arXiv 的兜底和单次下载 120 秒上限），457 条参考文献中 359 条拿到 PDF（78.6%），`run_en.sh` 改为带上 `en_papers/<name>/ref/`。

## 1. 端到端注入实验

### 1.1 总表

| 语料 | 版本 | 注入 | 检出 | 查全率 | 查准率（宽） | 查准率（严） | 剔除转换噪声后估计 | 干净稿既有报警 | 支持度确定判断覆盖 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 中文期刊综述 5 篇（docx） | F33，10 月 29 日 | 44 | 43 | 0.977 | 0.977 | 0.112 | 0.131 | 340 | 68.3% |
| 中文期刊综述 5 篇（docx） | **基线** | 44 | 43 | **0.977** | **0.956** | **0.133** | **0.152** | **279** | **71.7%** |
| 英文 arXiv 5 篇（LaTeX） | F8，10 月 24 日，deepseek-flash，无文献文件夹 | 42 | 39 | 0.929 | 0.975 | 0.183 | | 173 | 64.6% |
| 英文 arXiv 5 篇（LaTeX） | **基线**，qwen3.8-flash，文献文件夹 78.6% | 42 | 38 | **0.905** | **0.950** | **0.168** | | **186** | **85.1%** |
| 合计 | **基线** | 86 | 81 | **0.942** | **0.953** | **0.147** | | 465 | 975/1257 = 77.6% |

- 单元与口径同 `demo/testset/README.md`：一条引用句或一条参考文献为一个单元；宽口径把干净稿也报出的问题当作原文自身问题剔除，严口径全部计为误报。
- 英文前后两行的判断模型和原文来源都不同，不能当作 f36 的改进幅度。中文前后两行模型相同，差异来自 f36 的准确率修复：干净稿报警从 340 降到 279，主要是错别字修订（154→110 个单元）和真实性 mismatch（57→23）。
- 中文新增误报 2 条，都在 liuqiao_kg：r10、r68 在干净稿核验通过，注入稿里变成年份不一致。原因见第 4 节痛点 5。
- 剔除转换噪声后估计的口径见 1.4。英文是原始 LaTeX 源码，没有转换环节，不做这项估计。

### 1.2 按错误类型

| 类型 | 中文 | 英文 | 合计 |
| --- | --- | --- | --- |
| 伪造文献 fake_ref | 10/10 | 10/10 | 20/20 |
| 错年 wrong_year | 5/5 | 5/5 | 10/10 |
| 未引用条目 uncited | 5/5 | 2/2 | 7/7 |
| 引用堆砌 stacking | 5/5 | 5/5 | 10/10 |
| 错别字 typo | 9/9 | 10/10 | 19/19 |
| **张冠李戴 misattribution** | **9/10** | **6/10** | **15/20** |

漏检全部来自张冠李戴。

### 1.3 张冠李戴漏检清单（48 小时的核心靶子）

| 样本 | 换入的文献 | 结论 | 原因 | 归类 |
| --- | --- | --- | --- | --- |
| zh `luohuilan_odt` misattr1：YOLO9000 在 ImageNet 与 MS COCO[1] 上同步训练 | [1] Liu 等 2018 目标检测综述（应为 [46] COCO） | supported，全文 | 换入的是综述，全文确实描述了 YOLO9000 的 WordTree 联合训练，模型找到逐字证据。属于二手引用，构造标签有噪声 | 标签噪声 |
| en `en_resnet` misattr2：multi-scale testing following [17] | Jegou2011 乘积量化（应为 Ren2015a NoC） | partial，只有摘要 | 没有本地 PDF 只拿到摘要，模型认为"片段没写到"给了 partial，partial 是低严重度，不计为检出 | 原文缺失与严重度 |
| en `en_ddpm` misattr2：This material is from Harsha et al. (2007) | harsha2007communication（应为 sohl2015deep） | supported | 附录推导的公式在渲染时被去掉，抽出的论断只剩"This material is from"，残句无从核对 | 论断抽取残句 |
| en `en_vit` misattr1：running fine-tuning at different resolution than training is common practice | xie2020 Noisy Student（应为 kolesnikov2020 BiT） | supported，全文 | Noisy Student 确实在更大分辨率下微调，笼统背景句换上的文献也能支持 | 标签噪声 |
| en `en_vit` misattr2：also used Huang et al. (2020) averaging | huang2020 CCNet（应为 polyak） | supported，全文 | 证据只是学习率策略，理由里写了"averaging 通常指 EMA"，仍判支持，模型替论断找理由 | 判断错误 |

五处里两处是构造标签噪声，三处是系统问题。英文演示稿另有 4 处漏检，见 1.5。

### 1.4 干净稿报警噪音拆解

脚本 `demo/testset/analyze_clean_noise.py`，结果 `demo/testset/results/clean_noise.md` 与同名 `.json`。

干净稿发现与修订（五篇合计，含低严重度）：

| 层 | 中文 high | 中文 medium | 中文 low | 英文 high | 英文 medium | 英文 low |
| --- | --- | --- | --- | --- | --- | --- |
| authenticity | 24 | 25 | 21 | 4 | 10 | 16 |
| support | 69 | 11 | 51 | 52 | 1 | 14 |
| distribution | 0 | 21 | 5 | 0 | 31 | 22 |
| norms | 1 | 9 | 32 | 0 | 3 | 45 |
| 修订 typo | 114 | | | 69 | | |
| 修订 ref_reorder、marker_renumber | 0 | | | 0 | | |

F33 时中文干净稿有 465 条重排与重编号修订，来自尹宏鹏一篇表格的引用顺序；F35 的浮动体感知重排之后为 0，演示稿注入的重排仍然检出。

中文错别字修订按转换痕迹归类：

| 类别 | 条数 | 例子 |
| --- | --- | --- |
| space 只差空格 | 33 | Schoolof→School of，Gra m→Gram，Mausa m→Mausam |
| width 全半角与数字分隔 | 1 | 26 260→26,260 |
| hyphen 断行连字符 | 1 | 3dSOBS→3D-SOBS |
| formula 公式残片 | 8 | `! E`→`D_E`，烅→∑ |
| truncate 段首段尾截断 | 2 | roblems→problems，objec→objects |
| other 真错别字或模型误改 | 69 | 籍→借，attentions→attention，Wordnet→WordNet |

- 114 条中 45 条（39.5%）疑似 PDF 重建 docx 的转换痕迹。
- 单元口径上，279 个干净稿报警单元里 102 个只因错别字修订报警，其中 41 个全部是转换痕迹。剔除后估计查准率 = 43 / (43 + 2 + 279 − 41) = **0.152**。
- 这个估计仍把原稿真实问题算作误报。item bench 人工核对显示，中高严重度支持度报警中原稿真实错引约占 39%–60%（`item_bench/results.md` 第 10.8 节），真实查准率高于 0.152。要给出一个数，需要把干净稿报警人工标完（`precision_audit/`）。
- 严口径多出的报警第二大类是引用堆砌：中文 52、英文 63 个单元，集中在综述的相关工作部分。

### 1.5 决赛演示稿

| 演示稿 | 注入 | 检出 | 报告 |
| --- | --- | --- | --- |
| 中文：罗会兰《基于深度学习的目标检测研究综述》docx + 52 篇 PDF | 17 | **17/17** | `demo/final/runs/demo_v6_f36.json` |
| 英文：ResNet（arXiv 1512.03385）LaTeX + 29 篇 PDF，本次新建 | 16 | **12/16** | `demo/final/runs/en_v1.json` |

英文演示稿由 `demo/final/build_final_en.py` 生成 `demo/final/英文演示稿/deep_residual_learning.zip`，注入清单 `demo/final/injections_en.json`，核对命令 `python demo/final/check_final.py demo/final/runs/en_v1.json demo/final/injections_en.json`。注入类型与中文一一对应，参考文献重排不适用于 LaTeX。漏检的 4 处：

| 注入 | 结果 | 原因 | 代码位置 |
| --- | --- | --- | --- |
| author_swap：batch normalization (BN) by Glorot et al. [17] | 无报警 | 作者归属规则只看句中只有一个引用标记的句子，这句后面还有一个同样指向 [17] 的 following [17]，被跳过；支持度判断的证据未能逐字定位，降为无法判断 | `backend/citecheck/lint/attribution.py:100-106` |
| misattr_dataset：PASCAL VOC 2007 and 2012 [5] and COCO [39]，[39] 换成 ImageNet | supported | 一句多引，模型把 [39] 对到了 PASCAL VOC，用 ImageNet 论文里提到 VOC 的一句话作证据 | `support/claims.py:102` 论断按标记切分；`support/judge.py` |
| overclaim：Faster R-CNN [34], which runs at 50 frames per second | 没有论断 | We adopt X [n], which … 这类方法句没有抽出论断 | `support/claims.py:102` `_PROMPT` |
| number_bn：BN … with 140 times fewer training steps | supported | 理由里写明原文是 14 倍，标签仍是支持，标签与理由矛盾 | `support/judge.py:156` `check_details`，`support/layer.py:371` `_cascade` |

### 1.6 逐条扰动基准（item bench，只测支持度判断）

本次没有重跑。当前开发配置（融合检索加重排、只用 flash）在 item bench 上没有完整跑过，加了重排后片段变化，缓存大多不命中，预计花费 2 到 4 元，列为开赛第一批任务。最近两次全量结果（`demo/testset/item_bench/results.md` 第 10、14 节）：

| 版本 | orig 报警（期望不报） | swap 检出 | alter 检出 | 干净子集 orig 报警中原稿真问题 R / 误报 F |
| --- | --- | --- | --- | --- |
| ctx14_cascade：flash 首轮加 max 复核 | 50/424 | 232/424 | 75/174 | 12 / 13 |
| flash_fused：只用 flash，融合检索 | 73/424 | 245/424 | 77/174 | 11 / 23 |

扣除构造标签噪声后，swap 的实际检出率约 0.71，alter 约 0.6–0.7（第 10.3、10.4 节抽样估计）。

### 1.7 公开数据集

合并 f36 后在主缓存上回放，2819 次判断与复核全部命中缓存，逐项与 10 月 28 日、31 日一致，说明 f36 没有改动支持度判断。配置为 qwen3.8-flash 加硅基流动融合检索与重排。

| 数据集 | 标准准确率 | macro-F1 | 报警准确率 | 有问题的引用查出 | 参照 |
| --- | --- | --- | --- | --- | --- |
| Citation-Integrity 606 条，人工标注 | 0.617 | 0.421 | 0.73 | 106/236 = 0.45 | 原论文 GPT-4 上下文学习 0.65 / 0.45，不准确引用 F1 0.09，我们 0.30 |
| SemanticCite 分层抽样 400 条，GPT-4.1 标注 | 0.600 | 0.529 | 0.96 | 150/278 = 0.54 | 论文自报微调 Qwen3-4B 0.664 / 0.49（112 条） |

## 2. 速度与成本

脚本 `demo/testset/profile_cost_speed.py`，逐次运行记录在 `demo/testset/profile_runs/`，汇总 `demo/testset/results/cost_speed.md`。价格按百炼北京地域原价：qwen3.8-flash 输入 0.8、输出 2.7，qwen3.8-max 输入 12、输出 36，text-embedding-v4 与 qwen3-rerank 各 0.5，单位元每百万 token。

### 2.1 耗时

| 稿件 | 规模 | 冷启动 | 第一次复跑 | 稳定复跑 |
| --- | --- | --- | --- | --- |
| 中文演示稿 docx | 73 条文献、96 处引用、79 条论断、52 篇 PDF | **241.5 s** | 25.9 s | **5.4 s**（45 倍） |
| 英文演示稿 LaTeX | 54 条文献、142 处引用、112 条论断、29 篇 PDF | **472.9 s** | 65.7 s | **4.3 s**（110 倍） |

冷启动各层耗时（四层并发，从开始到该层结束）：

| 稿件 | 解析 | 真实性 | 支持度 | 分布 | 规范 |
| --- | --- | --- | --- | --- | --- |
| 中文演示稿 | 0.0 s | 164.1 s | 241.3 s | 56.0 s | 43.2 s |
| 英文演示稿 | 0.8 s | 36.3 s | 471.8 s | 20.2 s | 143.2 s |

- 支持度层决定墙钟。它要把每篇连上的 PDF 全文切片送去算向量（中文演示稿 1079 批、297 万 token），再重排、判断。
- 真实性层的瓶颈是外部检索：中文演示稿 Crossref 115 次请求累计 2994 s、OpenAlex 90 次累计 881 s、arXiv 6 次累计 252 s（并发请求耗时之和）。
- 第一次复跑仍有少量判断和重排没有命中缓存（中文 18 次判断、31 次重排），第二次复跑全部命中。冷启动时部分来源超时或限流，复跑时拿到的片段不同。
- 注入实验语料的冷启动（带文献文件夹）：GPT-3 600 s、ViT 454 s、T5 367 s，主要耗在上百篇 PDF 的向量上。

### 2.2 逐任务平均 token（主缓存库全部真实 Qwen 调用）

| 任务 | 模型 | 真实调用 | 平均输入 | 平均输出 |
| --- | --- | --- | --- | --- |
| structure 文献结构化 | qwen3.8-flash | 576 | 460 | 296 |
| extract 论断抽取 | qwen3.8-flash | 1282 | 160 | 67 |
| judge 首轮判断、细节复查、检索词 | qwen3.8-flash | 23529 | 1320 | 119 |
| review 复核 | qwen3.8-flash | 1685 | 2001 | 148 |
| review 复核 | qwen3.8-max | 2492 | 1999 | 106 |
| typo 错别字 | qwen3.8-flash | 2691 | 267 | 65 |
| function 引用功能 | qwen3.8-flash | 994 | 285 | 96 |
| profile 结构画像 | qwen3.8-flash | 139 | 1180 | 114 |
| overview 期刊评审 | qwen3.8-max | 16 | 805 | 224 |

完整表含 qwen3.7-flash 与向量、重排，见 `results/cost_speed.md` 第 1 节。

### 2.3 单篇冷启动成本

两篇演示稿冷启动的实际用量按百炼价格折算：中文 2.34 元，英文 2.38 元，其中向量分别 1.48、1.30 元，重排 0.46、0.59 元，所有对话模型合计 0.40、0.49 元。

标准论文（参考文献 35 条、正文引用 65 处、正文段落 40 个、论断 55 条、论断与文献配对 75 个、35 篇被引全文都能拿到）按两篇冷启动的单位频次折算：

| 任务 | 次数 | 配置 A：全 flash | 配置 B：复核用 max，触发 25%–35% |
| --- | --- | --- | --- |
| structure | 7 | 0.012 | 0.012 |
| extract | 12 | 0.004 | 0.004 |
| typo | 12 | 0.003 | 0.003 |
| function | 31 | 0.011 | 0.011 |
| judge | 202 | 0.178 | 0.178 |
| review | 13（B 为 19–26） | 0.025 | 0.510–0.714 |
| 向量 | 970 批 | 1.292 | 1.292 |
| 重排 | 63 | 0.299 | 0.299 |
| **合计（百炼向量与重排）** | | **1.82 元** | **2.31–2.51 元** |
| 合计（硅基流动向量与重排，约 0.14 元每百万 token） | | 0.68 元 | 1.16–1.37 元 |

- 实测复核触发率按论断与文献配对计：中文演示稿 19%，英文 16%，低于配置 B 假设的 25%–35%。
- 百炼价格下，向量占配置 A 的 71%，所有对话模型合计约 0.23 元。成本问题主要是向量问题，见痛点 4。
- 配置 B 接近产品默认配置。期刊对标（profile、overview）只在填写目标期刊时运行，不计入。
- README 原来写的"一次完整检查约 0.19 元"没有注明当时的模型配置和缓存状态，已改为本节数字。

### 2.4 现场接入本地 LLM 时要测的项

计划在会场加本地模型。为了与本节直接对照，建议每个方案都跑同一组命令，各测一次冷启动和一次稳定复跑：

```bash
python demo/testset/profile_cost_speed.py run --tag zh_local --cache /tmp/local_zh.sqlite \
    "demo/final/演示稿/基于深度学习的目标检测研究综述.docx" "demo/final/演示稿/ref"
python demo/testset/profile_cost_speed.py run --tag en_local --cache /tmp/local_en.sqlite \
    "demo/final/英文演示稿/deep_residual_learning.zip" "demo/final/英文演示稿/ref"
python demo/testset/profile_cost_speed.py report
python demo/final/check_final.py <报告> [demo/final/injections_en.json]
```

本地路由的调用在 `llm_usage` 里 provider 记为 mlx-local（换成新的本地引擎时沿用这一路由），模型名不是云端 Qwen 编号，`report` 第 3 节实际花费按 0 计；第 4 节标准论文表按云端价格折算，不区分本地。对照指标：冷启动墙钟、支持度层耗时、云端花费、演示稿检出数，以及注入实验的查全率与严口径查准率。

## 3. 汇总：48 小时前后对比表的起点

| 指标 | 开赛时（本基线） | 测法 |
| --- | --- | --- |
| 注入查全率 中文 / 英文 | 0.977 / 0.905 | `run_all.sh`、`run_en.sh`、`evaluate_corpus.py [en]` |
| 张冠李戴检出 | 15/20 | 同上 |
| 严口径查准率 中文 / 英文 | 0.133 / 0.168 | 同上 |
| 剔除转换噪声后估计（中文） | 0.152 | `analyze_clean_noise.py` |
| 干净稿既有报警单元 中文 / 英文 | 279 / 186 | 同上 |
| 支持度确定判断覆盖 中文 / 英文 | 71.7% / 85.1% | 同上 |
| 演示稿检出 中文 / 英文 | 17/17 / 12/16 | `check_final.py` |
| 冷启动 中文 / 英文演示稿 | 241.5 s / 472.9 s | `profile_cost_speed.py run` |
| 稳定复跑 中文 / 英文演示稿 | 5.4 s / 4.3 s | 同上 |
| 标准论文冷启动成本，配置 A / B | 1.82 元 / 2.31–2.51 元 | `profile_cost_speed.py report` |
| 本地运行的 AI 能力 | 0 | |
| Citation-Integrity 报警准确率 / 查出 | 0.73 / 0.45 | `external_eval.py ci` |

## 4. Top 5 痛点

按对路演指标的影响排序，每条给出失败样本和代码位置。

### 痛点 1：一句多引时，引用标记与论断片段对不上

- 样本：英文演示稿 misattr_dataset（`COCO [39]` 换成 ImageNet，模型拿 ImageNet 论文里提到 PASCAL VOC 的句子判为支持）；英文演示稿 author_swap（同句两个 `[17]`，作者归属规则跳过）；`en_vit` misattr2。
- 现状：论断抽取按句子给模型，模型自行决定每个标记管哪一段；判断时整句交给模型，模型可以拿论断中任意一部分去对证据。作者归属规则为了避免歧义，句中多于一个标记就不检查。
- 位置：`backend/citecheck/support/claims.py:102` `_PROMPT`；`support/judge.py:75` `judge_claim`；`lint/attribution.py:100-106`。
- 方向：按引用位置切出每个标记紧邻的短语（`COCO [39]` 只判"COCO 数据集"），判断时把它标为这篇文献负责的内容；同句标记都指向同一文献时，作者归属照常检查。与 `design/48小时提升路线.md` 4.2 第 4 条合并做。
- 指标：张冠李戴 15/20，英文演示稿 12/16。

### 痛点 2：标签与理由矛盾，数字不符放过

- 样本：英文演示稿 number_bn（理由写明原文是 14 倍，标签是支持）；中文演示稿 overclaim（Soft-NMS 提升 10 个百分点只给 partial，低严重度）；`en_resnet` misattr2（只有摘要时给 partial，低严重度，不计检出）。
- 现状：`check_details` 只在模型自己摘出不一致的原文句时送复核；理由里已经说不一致、标签却是支持时，没有任何规则拦下。
- 位置：`support/judge.py:156` `check_details`；`support/layer.py:371` `_cascade`。
- 方向：规则层的数字一致性检查。论断里归属给文献的数字（百分比、倍数、类别数、fps）在证据片段中出现了不同的同类数字时，强制送复核；理由文本含"不一致""存在差异"而标签为支持时也送复核。只决定是否复核，结论仍由模型给。

### 痛点 3：论断抽取漏句与残句

- 样本：英文演示稿 overclaim（`We adopt Faster R-CNN [34], which runs at 50 fps` 没有论断）；`en_ddpm` misattr2（附录公式被去掉后论断只剩"This material is from"）。
- 位置：`support/claims.py:102` `_PROMPT`；LaTeX 公式渲染在 `parse/latex/`。
- 方向：提示词补"方法沿用句里的定语从句和数字也是论断"；论断短于若干词或去掉标记后不成句时，向前合并上一句或标为无法判断并在报告里说明，不让残句得出支持。

### 痛点 4：冷启动慢、成本主要花在向量上

- 数据：中文演示稿冷启动 241.5 s，英文 472.9 s；百炼价格下向量占单篇成本 54%–71%；被引全文切片上传是隐私说明里最需要解释的一项。
- 位置：`backend/citecheck/llm/embed.py:54` `embed`；`support/sources.py` 片段排序；外部检索 `refs/sources.py`。
- 方向：本地向量（Intel 本地 AI 硬性要求，`design/Intel本地化移植方案.md`），被引全文上传降为 0，向量成本降为 0；或先用 BM25 预选候选窗口，只给候选算向量。外部检索给 Crossref 加更短的超时与并发上限，避免单源拖住真实性层。
- 指标：冷启动墙钟、单篇成本、被引全文上传量。

### 痛点 5：干净稿报警量大，严口径查准率低

- 数据：干净稿报警单元中文 279、英文 186；严口径 0.133 / 0.168。主要来源：错别字修订（中文 110、英文 64 个单元，中文其中约四成是转换痕迹）、引用堆砌（52、63）、不支持（63、43）。另有真实性规则的一处脆弱点：`refs/verify.py:786` `_year_horizon` 取稿件参考文献中第二晚的年份作为重新登记的判断上限，注入两条较新的伪造文献后上限被抬高，`liuqiao_kg` r10（文中 2012，数据库 2021）、r68（文中 2011，数据库 2018）从核验通过变为年份不一致，这是本次基线仅有的两条新增误报。
- 位置：`distribution/layer.py:209` 堆砌阈值 `len(ids) >= 5`；`lint/typos.py`；`refs/verify.py:786`。
- 方向：堆砌在综述与相关工作章节降为低严重度并折叠；错别字的拉丁词修订要求改后的词在全文出现过；年份上限改为只用核验通过的条目计算；人工标完干净稿报警（`precision_audit/`），把查准率从区间变成一个数。

## 5. 复现

```bash
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate claude
# 测试
cd backend && python -m pytest -q
cd app && npx vitest run && npm run typecheck && npm run lint:design
# 注入实验（reports/ 已有文件会跳过，重跑先移走）
bash demo/testset/run_all.sh && python demo/testset/evaluate_corpus.py
bash demo/testset/run_en.sh && python demo/testset/evaluate_corpus.py en
python demo/testset/analyze_clean_noise.py
# 英文文献文件夹
python demo/testset/item_bench/fetch_refs.py --reports reports en_resnet en_t5 en_gpt3 en_ddpm en_vit
# 演示稿
python demo/final/build_final.py && python demo/final/build_final_en.py
python demo/final/check_final.py demo/final/runs/demo_v6_f36.json
python demo/final/check_final.py demo/final/runs/en_v1.json demo/final/injections_en.json
# 速度与成本
python demo/testset/profile_cost_speed.py report
# 公开数据集（命中缓存时不花钱）
python demo/testset/item_bench/external_eval.py ci && python demo/testset/item_bench/external_eval.py score ci
```

f36 之前的报告另存在 `demo/testset/reports_f33/` 与 `results_f33/`，均只在本机。报告与 PDF 含被引文献原文，不入库。
