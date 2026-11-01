# 干净稿报警噪音拆解

由 `analyze_clean_noise.py` 生成，读 `reports/`。错别字归类规则见脚本文档。

## 中文 docx：干净稿报警（五篇合计）

| 层 | high | medium | low | 合计 |
| --- | --- | --- | --- | --- |
| authenticity | 24 | 25 | 21 | 70 |
| support | 69 | 11 | 51 | 131 |
| distribution | 0 | 21 | 5 | 26 |
| norms | 1 | 9 | 32 | 42 |

| 修订类型 | 条数 |
| --- | --- |
| typo | 114 |

错别字修订 114 条，其中疑似转换痕迹 45 条（39.5%）：

| 类别 | 条数 | 例子 |
| --- | --- | --- |
| space | 33 | 'Schoolof'→'School of'；'Gra m'→'Gram'；'Mausa m'→'Mausam'；'hi m'→'him' |
| width | 1 | '26 260'→'26,260' |
| hyphen | 1 | '3dSOBS'→'3D-SOBS' |
| formula | 8 | '! E'→'D_E'；'!'→'D'；'!'→'D'；'烅'→'∑' |
| truncate | 2 | 'roblems'→'problems'；'objec'→'objects' |
| other | 69 | 'attentions'→'attention'；'籍'→'借'；''→'属'；'Wordnet'→'WordNet' |

单元口径（与 evaluate_corpus.py 一致）：TP=43 新增误报=2 干净稿既有报警=279，其中只因错别字修订报警 102 个，全部是转换痕迹的 41 个。

- 查准率 宽 0.956　严 0.133　**剔除转换噪声后估计 0.152**

## 英文 LaTeX：干净稿报警（五篇合计）

| 层 | high | medium | low | 合计 |
| --- | --- | --- | --- | --- |
| authenticity | 4 | 10 | 16 | 30 |
| support | 52 | 1 | 14 | 67 |
| distribution | 0 | 31 | 22 | 53 |
| norms | 0 | 3 | 45 | 48 |

| 修订类型 | 条数 |
| --- | --- |
| typo | 69 |

错别字修订 69 条，其中疑似转换痕迹 4 条（5.8%）：

| 类别 | 条数 | 例子 |
| --- | --- | --- |
| space | 3 | 'film maker'→'filmmaker'；'however,make'→' however, make'；'USAToday'→'USA Today' |
| hyphen | 1 | 'human written'→'human-written' |
| other | 65 | ''→'y'；'expect'→'except'；''→'X '；'Table'→'Tables' |

英文稿件是 arXiv 原始 LaTeX 源码，没有 PDF 转换环节，上表的 space、width 类多是标点空格改动，不计为转换噪声，也不做剔除估计。
