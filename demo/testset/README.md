# 预 2021 人类稿件测试集（构造注入实验用）

目的：用 2021 年（大模型普及）之前人类撰写的真实论文做底稿，人为注入错误后跑四层体检，
按**论断-引用对**（一条引用句 × 其引用的一篇文献 = 一个数据点）统计查准率、查全率、准确率。
收集时间：2026-10-24。原始包不入 git（见 `.gitignore`），本目录其余文件入库。

## 英文语料（`raw/`，arXiv 源码包，产品原生支持 .tar.gz）

| arXiv | 论文 | 年份 | 正式发表 | 参考文献 | 参考文献组织 |
| --- | --- | --- | --- | --- | --- |
| 1512.03385 | Deep Residual Learning for Image Recognition (ResNet) | 2015 | CVPR 2016 | 50 | `.bbl` |
| 1910.10683 | Exploring the Limits of Transfer Learning with T5 | 2019 | JMLR 2020 | 133 | `.bbl` + `.bib` |
| 2005.14165 | Language Models are Few-Shot Learners (GPT-3) | 2020 | NeurIPS 2020 | 144 | `.bbl` |
| 2006.11239 | Denoising Diffusion Probabilistic Models (DDPM) | 2020 | NeurIPS 2020 | 72 | `.bbl` + `.bib` |
| 2010.11929 | An Image is Worth 16x16 Words (ViT) | 2020 | ICLR 2021 | 58 | `.bbl` + `.bib`（分 .tex 文件） |

五篇合计 457 条参考文献，全部带 arXiv 编译产物 `.bbl`（`demo/latex/README.md` 中的三种
参考文献组织方式都有覆盖）。下载命令：`curl -L -o <id>.tar.gz https://arxiv.org/e-print/<id>`。

## 中文语料（五家期刊各一篇高被引综述，全部 2021 年前）

| 论文 | 期刊 | 参考文献 | 列表来源 |
| --- | --- | --- | --- |
| 顾迎捷等《基于神经网络的机器阅读理解综述》 | 软件学报 2020, 31(7):2095-2126 | 130 | 官网 HTML 全文逐条 |
| 刘峤等《知识图谱构建技术综述》 | 计算机研究与发展 2016, 53(3):582-600 | 47 | 万方（分页抓取） |
| 尹宏鹏等《基于视觉的目标检测与跟踪综述》 | 自动化学报 2016, 42(10):1466-1489 | 227 | 官网 PDF 双栏抽取 |
| 罗会兰, 陈鸿坤《基于深度学习的目标检测研究综述》 | 电子学报 2020, 48(6):1230-1239 | 17* | 万方（万方仅数字化 17 条） |
| 赵阳洋等《任务型对话系统研究综述》 | 计算机学报 2020, 43(10) | 48 | 万方（分页抓取） |

五篇合计 469 条参考文献（中文 82 + 英文 387），逐条见 **`zh_references.md`**（含语言标注）。
原始数据在 `zh_refs/*.json`。已下载的官网全文 PDF 在 `zh_pdfs/`（自动化学报一篇；软件学报
有官网 HTML 全文；其余期刊官网被反爬/下线，底稿全文由知网下载）。

注意事项：

- 刘峤一篇的官网 PDF 是方正老排版（无 ToUnicode 文本层），机器不可抽文本；其参考文献以
  万方列表为准，稿件全文用知网下载版。
- 罗会兰一篇万方只有 17 条，与 10 页篇幅不符；以知网 PDF 的文后参考文献为准，下载后需
  人工补全 `zh_references.md` 中该篇的清单。
- 万方条目格式带其自有标点与 DOI 尾注，属来源原样，不做清洗。

## 中文底稿的知网下载清单

`zh_references.md` 中标注"中文"的 82 条 = 需要从知网下载的 PDF（放进各篇的 `ref/` 文件夹）。
英文 38 条/篇不等，无需知网：真实性核验与支持度证据走联网检索（Crossref/OpenAlex/S2/arXiv）。

## 指标设计（与 `demo/evaluate.py` 的关键差别）

评测单元从"整篇注入处"改为**论断-引用对**：

- 一条引用句（claim）与其引用的每篇文献构成一个对；一篇 130 条文献的综述经解析后可产
  生数百个数据点（zh_eval 实测：51 条文献 → 72 个对）。
- 构造时对底稿随机选中 k 个"论断-引用对"注入错误（类型沿用 `demo/injections.json` 的
  kind：`fake_ref` / `wrong_year` / `misattribution` / `uncited` / `stacking` / `typo` /
  `ref_reorder`），其余对保持原样。
- 判定（与 evaluate.py 检出规则一致，不放宽）：
  - 注入对应被系统标出（如 misattribution → 该对 SupportCheck=unsupported 且有高严重度
    support finding；wrong_year → RefCheck=mismatch 且 issue 含"年份"）；
  - 未注入对若被标为高/中严重度问题，计为误报（FP）。

统计口径（每篇底稿一份，全集汇总一份）：

- TP = 注入对中系统报异常的数量；FN = 注入对中未报的数量；
- FP = 未注入对中被报异常的数量（`undetermined`/`unverifiable` 不计 FP，单独报告；
  同时给一列 strict 口径把 undetermined 计入 FP）；
- Precision = TP / (TP + FP)，Recall = TP / (TP + FN)，
  Accuracy = (TP + TN) / (注入对 + 未注入对总数)。

## 后续步骤（本次未做）

1. 知网下载 82 条中文 PDF，按篇建 `ref/` 文件夹；中文底稿转 docx（PDF→docx 或按官网
   HTML 重建）。
2. 写通用注入脚本（参数化底稿，替代手写 `inject.py`），生成带注入的稿件副本。
3. 跑管线（`run_pipeline.py`）+ 新 evaluate（按对统计 P/R/Acc），结果落
   `demo/testset/results/`。
