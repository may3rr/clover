# Clover 项目全貌（供外部评审）

> 写于 2026-10-31，对应 `master` 分支 `3ef1093`。评审者不需要事先读过仓库里的任何文件，本文自成一体。
> 另有一个未合并的分支 `f36-accuracy-venue-rebench`（提交 `9ddeccc`，71 个文件，+3387/−405），内容见第 12 节，正文描述的是 master 的状态。

---

## 1. 一句话

Clover 是一个 macOS 桌面应用。作者拖入一篇论文（Word `.docx` 或 LaTeX 项目），它给出一份引用体检报告，并能导出一份新文件：实质性问题写成 Word 批注，错别字和参考文献重排这类机械性问题写成 Word 修订，作者在 Word 里逐条接受或拒绝。

- 工作代号 `citecheck`，代码、包名、环境变量都用这个名字；产品名 Clover。
- 参赛场景：天猫 AI 黑客松，效率进化赛道，阿里云特别赛题（基于 Qwen 的科研提效）。比赛要求全程使用 Qwen 系列模型。
- 许可证：PolyForm Noncommercial 1.0.0。
- 已发布 Apple 芯片版 dmg，未经 Apple 公证。

## 2. 要解决的问题

投稿前，作者需要手工核对三件事：参考文献是否真实存在、作者年份 DOI 是否写对；正文里每一处引用是否真的支持对应的说法；格式是否统一。大模型普及后，编造文献和张冠李戴的引用更常见，这些核对又最容易在截稿前被省掉。Clover 把核对自动化，判断和修改留给作者。

## 3. 产品原则（设计上的硬约束）

评审时请重点检查代码是否守住了这几条。

1. **机械性问题给修订，实质性问题只给批注。**
   - 可以生成修订的只有三类：错别字、参考文献重新排序、因重排而变化的正文引用编号（`Revision.kind ∈ typo | ref_reorder | marker_renumber`）。
   - 编造或信息不符的文献、引错文献、缺少支撑的论断、引用分布异常、引用堆砌，一律只写批注。
   - 绝不改写或生成正文，绝不自动删除或替换参考文献，绝不推荐“应该引用哪篇”。
2. **所有改动可撤销。** 原文件只读，导出为新文件；导出文件里的每处改动都是修订。
3. **证据可追溯。** 每个“支持/不支持”判断都附被引文献原文片段，片段必须能在原文中逐字找到，找不到就降级为“无法判断”（第 6.2 节）。
4. **不确定就说不确定。** 查不到的中文文献标“无法核验”，不标“不存在”；某个检索源超时或报错算“不可用”，不算“查无此文”。
5. **全程 Qwen。** 不接其他厂商的大模型。
6. **稿件隐私。** 整篇稿件不上传，在本机解析。云端只收到判断所需的片段，第 8 节逐项列出。

## 4. 技术栈与规模

| 层 | 选型 |
| --- | --- |
| 桌面壳 | Electron + electron-vite，TypeScript |
| 前端 | React 18 + TypeScript，Tailwind 只用布局类；颜色、字号、缓动全部走 `tokens.css` 的 CSS 变量 |
| 后端 | Python 3.11，FastAPI，本地服务 `127.0.0.1:8765`，由 Electron 主进程拉起 |
| docx 解析与写回 | lxml 直接读写 OOXML，python-docx 只作辅助 |
| PDF | pypdf，本机解析；不做 OCR，不处理 CAJ |
| 文献检索 | Crossref、OpenAlex、Semantic Scholar、arXiv 公开 API |
| 证据检索 | rank-bm25，可选融合 Qwen3 向量与重排 |
| 模糊匹配 | RapidFuzz |
| 模型 | 阿里云百炼 DashScope，OpenAI 兼容接口；可选 mlx-lm 本地小模型 |
| 存储 | SQLite：检索缓存、模型结果缓存、向量、用量、历史报告 |
| 测试 | pytest、vitest |
| 打包 | `npm run dist`：把 python-build-standalone 的 CPython 和后端依赖打进 `Clover.app`；推 `v*` 标签后由 GitHub Actions 构建并发布 |

代码规模：后端 `citecheck/` 约 17,200 行 Python，前端 `app/src/` 约 13,400 行 TS/TSX。git 历史 184 个提交。

测试现状（本次在 master 上实跑）：
- 后端 `python -m pytest -q`：**482 passed, 3 skipped**，耗时 5 分 15 秒（合入 F36 后，2026-11-01）。
- 前端 `npx vitest run`：**72 passed**。
- 另有 `npm run lint:design`，用脚本检查组件里有没有颜色字面量、缓动字面量等设计规范违规。

## 5. 目录结构

```
backend/
  config.example.toml       模型名、接口、开关（代码里不写死模型名）
  citecheck/
    schema.py               Pydantic 数据模型，前端 TS 类型由它的 JSON Schema 生成
    config.py               读 .env 与 config.toml
    cache.py                SQLite：kv / vectors / llm_usage / reports 四张表
    pipeline.py             编排：解析 → 四层并发 → Report
    server.py               FastAPI 接口
    parse/                  docx 解析；parse/latex/ 为 LaTeX 解析
    library/                文献文件夹：PDF 扫描、元数据、与参考文献一对一连接、刊名识别
    refs/                   参考文献结构化与真实性核验
    support/                论断抽取、原文获取、支持度判断、证据逐字校验
    distribution/           引用分布、引用堆砌、期刊对标（范文池、指标、登记表）
    lint/                   规范检查、错别字、参考文献重排、作者归属、期刊硬性要求
    overview/               期刊评审（整体定位）
    export/                 写回 docx（批注 + 修订）、导出 LaTeX 项目 zip
    llm/                    模型调用唯一入口：client / router / local / embed / rerank
  benchmarks/               arXiv cs.CL 对标数据；venues/<id>.toml 期刊登记表
  tests/                    pytest 测试与 fixtures
app/
  src/main/index.ts         主进程：拉起后端、窗口、文件拖放
  src/preload/              预加载桥
  src/renderer/src/
    screens/                Empty / Onboarding / Scanning / LibraryConfirm / Running / ReportScreen / Detail / Settings / Error
    components/             侧栏图标、骨架屏、三点轨道动画等
    styles/tokens.css       唯一的设计 token 来源
  site/                     产品主页：在浏览器里原样运行应用界面，后端用模拟数据替代
demo/
  testset/                  量化评测语料、注入脚本、评测脚本与结果
  latex/                    LaTeX 样例集
```

## 6. 一次体检怎么跑

### 6.0 总体流程

```
拖入文件
  └─ 解析（docx 或 LaTeX）→ 章节、段落、引用标记、参考文献原文
       └─ 参考文献结构化（模型补全字段，字段必须能在条目原文里找到）
            ├─ [文献文件夹] PDF 扫描 → 与条目一对一连接 → 用户确认
            ├─ 真实性层 ──逐条完成即触发──→ 支持度层
            ├─ 分布层（含期刊对标的范文池）
            └─ 规范层（错别字、重排、规则检查）
       └─ 期刊评审（可选，四层结束后）
  └─ Report → 报告页 → 导出 docx / LaTeX zip
```

- 四层并发执行，各自包一层异常处理：一层失败只把该层标为 failed，其余照常出结果。真实性层失败时支持度层仍运行，此时全部判为无法判断。
- 支持度层不等真实性层全部跑完：每条参考文献核验结束（`on_ref` 回调）就开始判断引用它的论断。
- 前端通过 SSE（`GET /jobs/{id}/events`）接收进度：`parsed`（大纲，用于骨架屏）、`layer`（每层状态与问题数）、`progress`（每层进度，节流到 0.25 秒一次）、`done` / `failed`。
- 云端调用走一个带优先级的信号量（`PrioritySemaphore`），参考文献结构化优先于论断抽取。

### 6.1 解析

**docx**（`parse/`）
- 用 lxml 读 `word/document.xml`，每个段落保留字符偏移，后续高亮、批注、修订都按偏移定位。
- 把 Word 用户看得到、但 XML 里不是字面文本的内容作为“虚拟片段”补进段落：自动编号标签（`[1]`、`3.2`，从 `numbering.xml` 解析）、脚注尾注上标。
- 章节：先看标题样式，没有样式再用编号正则；编号必须承接上一个标题才算标题。再按中英文关键词表映射到 `intro | related | method | experiment | discussion | conclusion | other`。
- 引用标记按可靠程度依次识别：Zotero / EndNote / Mendeley / NoteExpress 域代码；上标数字；正文正则（`[1]`、`[1,3]`、`[2-5]`、`(Smith, 2020)`、`张三等(2020)` 等）。
- 参考文献区：按“参考文献 / References”标题、Zotero 文献域或末尾的编号串定位。三者都找不到时问一次便宜的模型列表从哪里开始，模型给出的范围必须能用规则复核。
- 表格逐格变成带坐标的段落（`Paragraph.cell`），插图挂在题注段落上。单元格不参与论断抽取和引用堆砌检查。

**LaTeX**（`parse/latex/`）
- 输入可以是 `.zip` / `.tar.gz` / 文件夹 / 主 `.tex`，压缩包先安全解压到缓存目录。
- 流程：定位主文件 → 去注释 → 展开 `\input` / `\include` → 展开条件 → 改写 cite 别名 → 切出正文 → 分块（段落、标题、`thebibliography`）→ 剥离浮动体、保留 `\caption` → 解析参考文献（`\bibitem`、`.bib` 或 `.bbl`）→ 按引用样式渲染。
- 每一步都在带偏移映射的 `Src` 对象上做，渲染后的任一字符都能追溯到 `文件:行号`。

### 6.2 文献真实性层（`refs/`）

1. **结构化**：先用正则抽标题、作者、年份、DOI，再让模型对每条重新结构化。模型给出的字段必须能在条目原文里找到。`.bib` 来的条目本身是结构化数据，跳过这一步。
2. **检索**：Crossref、OpenAlex、Semantic Scholar 并行查询；没核验上的再走 arXiv 批量标题查询（每次最多 5 个标题，全进程至少间隔 3 秒），最后按作者定向查一轮。每个请求都有超时、重试和缓存，Crossref 带 `mailto`，OpenAlex 支持多个 key 轮换。
3. **匹配**：标题用 `token_sort_ratio`，再比首作者姓氏和年份（允许差 1 年）。标题对上、但首作者和年份都对不上的记录，视为同名的另一篇论文，直接丢弃，不报“信息不符”。
4. **状态**：
   - `verified`：标题、首作者、年份都对上。
   - `mismatch`：找到了这篇，但有字段对不上，或写明的 DOI 指向另一篇。`issues` 里写具体哪一项。
   - `not_found`：只给英文文献。Crossref、OpenAlex、arXiv 都真正返回了结果且都没有匹配。
   - `unverifiable`：中文文献查不到，或三个必需源中有一个不可用。
5. **本地 PDF**：连上了本地 PDF 的条目，还要和 PDF 封面上的元数据比对。

### 6.3 论断支持度层（`support/`）

这是产品里最难、调得最多的一层。

1. **论断抽取**（`claims.py`）：把句子里的引用标记标成 `⟦mN⟧`，问 `extract` 模型每个标记支撑句子里的哪一段。返回的论断必须是原句的逐字子串，否则退回整句。这个任务是唯一允许走本地 mlx 模型的任务，本地失败自动回退云端。
2. **获取被引原文**（`sources.py`、`library/source.py`），按优先级：
   - 用户文献文件夹里连上的本地 PDF（标注页码）；
   - Semantic Scholar 的 openAccessPdf 或 arXiv PDF（不超过 20MB）；
   - OpenAlex / S2 / arXiv 摘要；
   - 都拿不到时 `source_kind=none`，不问模型，直接判为无法判断。
3. **挑片段**：全文切成约 3 句的窗口，用 BM25 打分；开启向量检索时，BM25 与 Qwen3-Embedding 相似度做倒数排名融合（RRF，k=60）；开启重排时，对前 40 个候选再跑一次 Qwen3-Reranker。首轮片段约 2500 字、最多 5 个窗口，复核片段约 6000 字、最多 12 个窗口。片段前面固定加上文献开头约 600 字，并去掉 arXiv 侧边水印。
4. **判断级联**（`layer.py`、`judge.py`）：
   - 首轮用 `judge` 模型（flash），输入论断、稿件里的这条参考文献、被引文献标题和片段，输出 `{label, evidence, rationale}`。
   - 首轮判 partial / unsupported，或指出“说的不是同一项工作”（off_topic），就交给 `review` 模型（max）复核。复核读更宽的片段，同时带上同一句里一起被引的其他条目。
   - 首轮判 supported 时，flash 再单独做一次细节核对；如果找到一句可定位的原文与论断某个细节矛盾，也送复核。
   - 复核接口失败时改用 `review_fallback` 模型重试一次，仍失败就保留首轮结论。
   - 可选的双片段判断（`[support] dual_excerpt`，默认关）：报警后再用纯 BM25 片段判一次，两次都报警才保留。
5. **证据逐字校验**（`evidence.py`，不可跳过）：两边都做 NFKC 归一化、压缩空白、统一引号，然后做子串匹配。另外兼容 PDF 抽取的三种痕迹：行末连字符断词、pypdf 把单词拆开、按顺序拼接的省略号片段（每一段都要逐字出现）。仍匹配不上时，模型会被要求重抄一次原文，再失败就把 `label` 降为 `undetermined`，并在 `rationale` 里写明“证据未能在原文中定位”。
6. **生成问题**：unsupported 为高严重度；off_topic 为中，批注标题写“可能引错了文献”；partial 降为低严重度（第 10 节解释原因）。每条拿不到原文的参考文献给一条低严重度提示。
7. **作者归属规则**（`lint/attribution.py`，不调模型）：正文写“徐增林等人[5]”“Vaswani et al.[6]”，但 [5]、[6] 的第一作者对不上，直接报“可能引错”。只在归属词紧挨着唯一一个数字标记时才判定，跨文种不判。

### 6.4 引用分布层（`distribution/`）

- **默认基线**：150 篇 arXiv cs.CL 论文的 LaTeX 源码，统计各章节引用占比、每千词引用密度、每句引用数的中位数和四分位距（`benchmarks/arxiv_cs_cl.json`）。
- 稿件指标落到四分位距之外才报，措辞是描述性的，严重度为低，挂在章节标题上。中文稿对英文基线时只比较占比，不比密度。
- **引用堆砌**：一句话引了 5 篇及以上。
- **引用功能分类**：模型把每处引用归为背景、方法、对比、结果、批评五类之一。
- **期刊对标**（可选，在首页填写目标期刊或会议名称后开启）：
  - 名称先到 `benchmarks/venues/` 登记表里按名称和别名解析，登记表外的名称也能用。
  - 范文池只取已经拿到原文的论文，不额外检索：一是稿件参考文献里属于目标期刊的条目，二是文件夹里未被引用的同刊 PDF。判断条目属于哪个期刊，依据结构化刊名、Crossref/OpenAlex 刊名、DOI 前缀、PDF 封面和整条著录；规则认不出的刊名交给模型做选择题，答案只能从列出的刊名里选。
  - 综述和研究论文分开对标。能统计的范文少于 3 篇时不对标，报告里写明找到了几篇、缺什么、下一步怎么做。
  - 逐篇比较六组指标：章节结构、引用位置、参考文献构成、引用功能构成、研究要素、篇幅与图表。每个数值都记下来自哪篇范文的哪一页、哪一行。
  - 研究要素（是否有消融实验、数据集个数等）只从标题、摘要、章节标题和图表题注里读，每个值都要附逐字证据，定位不到就记为无法判断。
  - 违反 `venues/<id>.toml` 里的硬性投稿要求时，在规范层给批注；偏离范文常态时，在分布层给批注。两者都不产生修订，也不推荐该引哪篇。

### 6.5 格式规范层（`lint/`）

规则检查，不调模型：
- 参考文献未被正文引用；正文引用找不到条目；条目重复（标题相似度 ≥95）；
- 混用数字编号与作者-年份两种格式；GB/T 7714 文献类型标识（[J]、[M]）有的写有的不写；
- GB/T 7714 期刊条目缺卷期或页码；
- 文献由 Zotero / EndNote 管理且顺序与首次引用顺序不一致时，只给提示，不重排。

**错别字**（`typos.py`，每段调用一次 `typo` 模型），对模型返回值逐项把关：
- 原文片段必须在段落中恰好出现一次；
- 改动数字、覆盖引用标记、改动后与原文相同，一律丢弃；
- 先求最小编辑区间，英文扩展到整个单词；
- 改动所在的中文三字窗口在全文出现两次以上，视为作者的术语，丢弃；
- 编辑距离大于 2 的不生成修订，改为一条低严重度批注“疑似笔误，请确认”。

**参考文献重排**（`reorder.py`，确定性算法）：
- 数字编号按正文首次引用的顺序排；作者-年份按首作者姓氏排，中文按拼音。
- 用最长递增子序列找出不需要移动的条目，只移动其余条目，修订数量最少。
- 正文标记重新编号后合并区间，例如 `[2-5]` 重排为 2、3、4、7 时写成 `[2-4,7]`。保留原来的括号、连字符和分隔符样式。
- 引用由文献管理软件维护时，一律不重排。

### 6.6 期刊评审（`overview/`，可选）

从范文池里挑主题最接近的几篇。flash 为每篇范文和稿件各读出一份“结构画像”，max 对比这些画像和四层的问题，按维度给出档位，再写两三句方向性意见。刻意只给档位，避免用户把它当成修改指令。

### 6.7 文献文件夹（`library/`）

- 文件夹结构：根目录放论文 docx，`ref/` 放被引 PDF；也可以拖入 docx 后再单独指定文献文件夹。
- **元数据**，按可信度依次取：知网网络首发封面 → 正式刊出页的“引用本文”条目 → 前两页的 DOI 或 arXiv 号 → 第一页最大字号的文字 → PDF 元数据 → 文件名。结果按文件内容哈希缓存。
- **连接**：给每对（条目，PDF）打分。DOI 相同直接 100 分；条目标题与 PDF 标题比对，并看标题是否逐字出现在 PDF 前几页；首作者必须出现，年份差超过 1 年算冲突。按分数贪心分配，保证一对一。分数居中的候选交给模型做三选一或都不是的选择题，模型选出的连接都标记为待用户确认。
- 用户在**连接确认页**核对连接、勾选或剔除对标范文。

### 6.8 导出

**docx**（`export/writer.py`）：复制原 zip，只改写必要的部件。处理顺序是为了避免偏移漂移：
1. 按段落收集所有锚点边界，一次性切分 run；
2. 把每个锚点解析成具体的 run 列表；
3. 写行内修订（`w:del` + `w:ins`，作者为 Clover）；
4. 写参考文献移动：原段落整段删除，在新位置整段插入；
5. 最后写批注，挂在被移动条目上的批注落到插入的副本上。

会让 Word 报“文件已损坏”的 OOXML 顺序约束都在代码里处理了，例如 rPr 里 `w:ins` / `w:del` 必须排在最前，`w:id` 和批注 id 从文档现有最大值往上加。导出后用解析器把新文件重新读一遍作为校验。批注正文分三行：问题、依据或证据、建议方向。

**LaTeX**（`export/latex.py`）：生成一个新的项目 zip。每条问题写成 `%` 注释，插在对应源码行上方；错别字修正放进 `clover-revisions.patch`，作者审阅后可以 `git apply`；源码本身不改。参考文献重排不适用于 LaTeX，因为顺序由编译决定。

## 7. 模型调用

所有调用都经过 `llm/client.py` 的 `chat_json(task, messages, Schema)`，业务代码不直接调 SDK。

- 判断类任务 `temperature=0`，要求 JSON 输出并用 Pydantic 校验，校验失败重试一次，再失败记为 `undetermined`。
- 缓存键为 `模型名 | sha256(模型名 + prompt)`。模型结论长期保留，改 `cache_version` 才失效；检索结果 30 天过期。
- 每次调用都把 token 用量写进 `llm_usage` 表，设置页显示花费。

`config.example.toml`（发布默认）的任务与模型：

| 任务 | 模型 |
| --- | --- |
| judge 支持度首轮、typo 错别字 | qwen3.8-flash |
| review 复核 / review_fallback | qwen3.8-max / qwen3.7-max |
| extract 论断抽取、structure 文献结构化、function 引用功能 | qwen3.7-flash |
| profile 结构画像 | qwen3.8-flash |
| overview 期刊评审 | qwen3.8-max |
| 向量 | 百炼 text-embedding-v4 |
| 重排 | 百炼 qwen3-rerank |
| 本地（默认关闭） | mlx-community/Qwen2.5-3B-Instruct-4bit，只服务 extract |

开发机上的 `config.toml` 不入库，目前为了省钱全部用 flash，向量和重排走硅基流动的 Qwen3-Embedding-0.6B 和 Qwen3-Reranker-0.6B。

费用（`PRE_HACKATHON_BASELINE.md` 第 2 节，空缓存实测后折算）：一篇参考文献 35 条、被引全文都能拿到的标准论文，按百炼原价全 flash 约 1.82 元，复核改用 max 并按 25%–35% 的论断与文献配对触发约 2.31–2.51 元。其中向量约 1.29 元，所有对话模型合计约 0.23 元，成本主要在向量。两篇决赛演示稿冷启动实际用量折合 2.34 元（中文）与 2.38 元（英文）。

评测脚本的一处历史问题：F36 之前 `demo/testset/run_all.sh`、`run_en.sh` 把 DeepSeek 密钥写进 `DASHSCOPE_API_KEY`，10 月 24 日的英文注入结果实际由 deepseek-flash 判断。基线定格时已修正并全部用 qwen3.8-flash 重跑。

## 8. 隐私与安全

**总述**：原始排版文件（.docx/.tex）与本地 PDF 全程驻留本机解析，不上传完整原文件；云端仅按需接收切片文本，包括错别字逐段检查的正文段落、带引用的论断句、参考文献条目原文，以及需复核的论断与证据片段。README 与本节已按这个口径改写（基线定格 v0.9-pre-hackathon）。

**始终发送的三项**（不受开关控制，体检必需）：
- 错别字检查：逐段发送正文段落。
- 论断抽取：发送带引用的句子。
- 文献结构化：发送参考文献条目原文。

**按开关发送的项**（用户在设置页可以关闭）：
- 支持度复核：需要复核的论断和证据片段。
- 向量检索：被引文献正文切成的片段、论断句和检索词。
- 重排：每条论断的候选片段。
- 期刊对标细化：范文的标题、摘要、章节标题、图表题注和含引用的句子；稿件的标题、摘要、章节标题和图表题注。刊名不明的 PDF 发首页开头和结尾各几百字。
- 填写目标期刊时：用户填的名称，以及规则认不出的刊名。
- 期刊评审：几篇范文的正文开头。

**本机安全**：
- 后端只监听 `127.0.0.1`。主进程启动时生成一个 32 字节的随机 token，经环境变量传给后端；除 `/health` 外，每个请求都要带 `x-citecheck-token` 请求头或 `token` 查询参数。
- CORS 设为 `allow_origins=["*"]`，靠 token 做鉴权。
- 渲染进程 `contextIsolation: true`、`nodeIntegration: false`、`sandbox: false`。
- API Key 只保存在 `~/Library/Application Support/Clover/.env`。

## 9. 前端

- 窗口：`titleBarStyle: hiddenInset`，`vibrancy: sidebar`，最小 1100×720。
- 屏幕：首次引导（填 API Key）→ 首页（拖入文件、填写目标期刊、历史报告）→ 扫描 → 连接确认 → 运行（四层进度、骨架屏）→ 报告页 → 详情 → 设置。
- 报告页三栏：
  - 左侧栏 240px，按图层筛选，显示各层问题数；
  - 中间阅读区按论文排版显示正文，有问题的片段用柔和底色高亮，表格和图片照原样显示；
  - 右侧检查器 380px，列出问题，点开进入详情。
- 支持度详情：上方是“你的论文写道”，下方是被引原文，证据位置高亮，最后给结论和理由。真实性详情：左右对照“你写的”和“数据库里查到的”，不一致的字段高亮。
- 设计规范写得很严（Notion 风格的暖中性色、只用系统字体、字号六档、不用分割线和边框、间距和圆角取固定值、缓动只在 token 里定义），由 `lint:design` 脚本自动检查。
- `app/site/` 把同一套渲染代码放进浏览器，后端换成模拟数据，作为产品主页和录屏素材。

## 10. 评测

### 10.1 注入实验（端到端，整条管线）

做法：取 2021 年以前人类撰写的真实论文做底稿，程序化注入六类错误。干净稿和注入稿各跑一遍完整管线，以一条引用句或一条参考文献为一个数据点统计。注入点只选在干净稿上能产出论断、能核验上、能拿到原文的位置，所以这个实验测的是检出能力；解析盲区和原文覆盖率另外报告。

| 语料 | 注入 | 检出 | 查全率 | 查准率（宽） | 查准率（严） | 支持度确定判断覆盖 |
| --- | --- | --- | --- | --- | --- | --- |
| 中文期刊综述 5 篇（docx，合入 F36 后重跑） | 44 | 43 | 0.977 | 0.956 | 0.133 | 71.7% |
| 英文 arXiv 论文 5 篇（ResNet、T5、GPT-3、DDPM、ViT，LaTeX，带 359 篇开放获取 PDF） | 42 | 38 | 0.905 | 0.950 | 0.168 | 85.1% |

- 2026-11-01 基线，全部任务 qwen3.8-flash。中文与 F33 相比查全率不变，干净稿报警从 340 降到 279，严口径从 0.112 升到 0.133；英文旧数字由 deepseek-flash 判断且没有文献文件夹，与新数字不可直接比较。
- 按类型：伪造文献、错年、未引用条目、引用堆砌、错别字全部检出；漏检的 5 处都是张冠李戴（中文 9/10，英文 6/10），逐条原因见 `PRE_HACKATHON_BASELINE.md` 1.3。其中两处换入的文献确实也能支持论断，属于构造标签噪声。
- 干净稿报警（中文 279、英文 186 个单元）还没有逐条人工核对。中文干净稿 114 条错别字修订中 45 条疑似 PDF 重建 docx 的转换痕迹，按单元剔除后中文查准率估计为 0.152（`demo/testset/analyze_clean_noise.py`）。
- 决赛演示稿：中文 17/17；新建的英文演示稿（ResNet LaTeX）12/16，漏检集中在一句多引、标签与理由矛盾和论断抽取漏句。

### 10.2 逐条扰动基准（只测支持度判断）

五篇中文论文，被引文献全部是本地 PDF，共 1022 个样本：
- orig 424 条：原稿的论断-引用配对，期望不报警；
- swap 424 条：把引用换成参考文献表里相邻的另一篇，期望报警；
- alter 174 条：让模型改动论断里的一处细节，期望报警。

主要发现：
- 给判断模型补上稿件里的这条参考文献、文献开头和可读的标题，swap 检出从 0.453 升到 0.667。
- flash 首轮加 max 复核：orig 报警减少约 42%，alter 检出不变，全量复核约 11 元。
- 逐条人工核对 orig 报警发现，金标论文本身有 12 处真实错引，例如把 F1 提升 1.2 写成 5.5、引错了 Transformer 的出处。所以 orig 报警不能直接算误报。
- 当前代码（ctx14_cascade）在干净子集上：orig 报警 31 条，其中真实问题 12 条、误报 13 条。中、高严重度报警里真实问题约占 60%。扣除标签噪声估计，swap 实际检出约 0.71，alter 约 0.6–0.7。
- 剩下的误报主要是 partial（片段只覆盖论断的一半），因此 partial 降为低严重度：照常导出批注，但阅读区默认不高亮，也不计入章节问题数。
- 检索评测：向量检索让关键原文的首轮命中率从 0.38 升到约 0.5；4B 向量模型没有比 0.6B 更好。
- 判断不稳是更大的问题：两组只换了检索方式，在 56 条结论不一致的样本里，41 条与检索无关，片段稍有变化，flash 的结论就翻转。结论是：降低误报，max 复核比双片段判断有效得多。

### 10.3 公开数据集

合入 F36 后在缓存上回放，结果逐条不变。

| 数据集 | 标准准确率 | macro-F1 | 报警准确率 | 有问题的引用查出 |
| --- | --- | --- | --- | --- |
| Citation-Integrity（Sarol 等 2024，606 条，人工标注），融合检索 + 重排，只用 flash | 0.617 | 0.421 | 0.73 | 106/236 = 0.45 |
| SemanticCite（Haan 2025），分层抽样 400 条，标签由 GPT-4.1 生成 | 0.600 | 0.529 | 0.96 | 150/278 = 0.54 |

- 原论文在 Citation-Integrity 上报告 GPT-4 上下文学习 micro-F1 0.65、macro-F1 0.45，“不准确引用”一类 F1 只有 0.09，我们是 0.25–0.30。同一研究中，人工标注员之间的 Cohen's κ 只有 0.18–0.31，这个任务本身就很难标准化。
- SemanticCite 开源的微调 Qwen3-4B 判断模型，在 Citation-Integrity 上报警多出一倍，报警准确率只有 0.50，所以没有接入产品。

### 10.4 期刊对标细化

样本是《数据分析与知识发现》38 篇 PDF：37 篇识别出刊名；175 个一级章节标题，规则加模型归类正确 98%；消融实验要素与全文关键词检查一致 94%。三轮验证共花费约 0.25 元。

## 11. 已知局限与风险

1. **张冠李戴是最大的盲区。** 全部漏检都来自这一类；拿不到被引原文时（基线覆盖率中文 71.7%、英文 85.1%）完全依赖作者归属规则；一句多引时引用标记与论断片段对不上是新的主要漏检原因。
2. **判断不稳定。** 同一论断换一份片段，flash 的结论可能翻转。目前靠 max 复核压低误报，代价是钱和时间。
3. **严口径查准率很低。** 干净稿上的大量报警尚未人工核对，真实误报率不清楚。对真实用户来说，一篇稿件上百条提示可能造成负担。
4. **中文文献核验弱。** Crossref / OpenAlex 对中文期刊覆盖差，没有文献文件夹时大多只能标“无法核验”。
5. **测试稿由 PDF 重建。** 两栏交错、残句、公式线性化等转换痕迹污染了部分评测结果，真实 docx 稿件里应该少见。
6. **解析规则仍有已知坑。** “Proc. of the 2014 Conf.”里的年份已在 F36 修正；重新登记年份的判断上限取稿件第二晚的年份，稿件里有较新的伪造条目时上限被抬高，真实条目会被误报年份不一致（`refs/verify.py` `_year_horizon`）。
7. **只支持 macOS Apple 芯片**，应用未经 Apple 公证。
8. **依赖外部 API**：Crossref、OpenAlex、S2、arXiv 的限流和可用性直接影响核验结果；超时的源会让条目落到“无法核验”。
9. **模型名带具体版本**（qwen3.8-flash 等），不同时间点的评测结果可能不可比。
10. **冷启动慢**：中文演示稿 241 s、英文演示稿 473 s，支持度层的向量计算和真实性层的外部检索是瓶颈；同一篇复跑全部命中缓存时 4–6 s。

## 12. F36 分支（已合入）

`f36-accuracy-venue-rebench` 已于 2026-11-01 合入 master，标签 `v0.9-pre-hackathon` 为决赛前基线，数字见 `PRE_HACKATHON_BASELINE.md`。改动包括：
- **准确率**：作者和标题比对忽略变音符（Jégou / Jegou）；记录年份晚于稿件最新引用年份时视为重新上传，不算错年；演讲、博客、排行榜归为灰色文献；去掉空格后相同的标题也算匹配；去掉标题里 PDF 断行的连字符；“Proceedings of the 2014” 里的年份不算出版年；错别字丢弃只改标点的修改；Mendeley 和 NoteExpress 域代码也视为文献管理软件维护。
- **产品**：新增 `POST /reports/{id}/venue`，体检完成后再填写期刊也能补做对标；Word 批注引用已定位的证据原文；报告页和导出弹窗的计数统一；连接确认页可以逐条确认模型选出的连接。
- 还包括一批界面细节修复和仓库清理。

## 13. 本地接口一览（`server.py`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 健康检查（免 token） |
| POST | `/analyze` | 上传稿件，返回 job_id |
| GET | `/jobs/{id}/events` | SSE 进度 |
| GET | `/jobs/{id}/report` | 完整 Report |
| POST | `/jobs/{id}/export` | 导出 docx / LaTeX zip |
| GET / DELETE | `/reports`、`/reports/{id}` | 历史报告列表、读取、删除 |
| POST | `/reports/{id}/export` | 从历史报告重新导出 |
| POST / GET | `/library/scan`、`/library/scan/{id}` | 扫描文献文件夹 |
| POST | `/library/venue` | 识别目标期刊、生成范文候选 |
| GET | `/benchmarks`、`/venues` | 对标领域、期刊登记表 |
| GET / PUT | `/prefs`、`/config` | 偏好与配置（含开关、API Key） |
| GET | `/usage`、`/models` | 用量与花费、可用模型 |
| GET | `/assets/{bundle}/{name}` | 稿件插图 |

## 14. 数据模型（`schema.py` 摘要）

```python
Section:        id, title, canonical
Paragraph:      id, section_id, text, char_offset, math, cell, images, caption
CitationMarker: id, paragraph_id, start, end, raw, ref_ids
Reference:      id, raw, title, authors, year, venue, doi, lang      # lang ∈ en|zh|other
RefCheck:       ref_id, status, matched, issues                       # verified|mismatch|not_found|unverifiable
Claim:          id, paragraph_id, start, end, text, marker_ids
SupportCheck:   claim_id, ref_id, label, evidence, source_kind, rationale
                # label ∈ supported|partial|unsupported|undetermined；source_kind ∈ abstract|fulltext|none
Finding:        id, layer, severity, anchor, title, detail, refs      # 导出为批注
Revision:       id, kind, anchor, old, new, reason                    # 导出为修订；kind ∈ typo|ref_reorder|marker_renumber
Report:         document, sections, paragraphs, markers, references,
                ref_checks, claims, support_checks, distribution, findings, revisions
```

前端的 TS 类型由这里导出的 JSON Schema 生成（`npm run gen:types`），不手写第二份。

## 15. 怎么复现

```bash
# 后端
cd backend
cp .env.example .env              # 填 DASHSCOPE_API_KEY；可选 SILICONFLOW_API_KEY、CROSSREF_MAILTO
cp config.example.toml config.toml
pip install -e ".[dev]"
python -m pytest -q               # 约 5 分钟，网络相关测试使用录制的响应

# 桌面应用（Node 22）
cd ../app
npm install
CITECHECK_PYTHON=$(which python) npm run dev
npm test && npm run typecheck && npm run lint:design

# 评测（需要 API Key，会产生费用）
bash demo/testset/run_all.sh clean && python demo/testset/inject_corpus.py \
  && bash demo/testset/run_all.sh injected && python demo/testset/evaluate_corpus.py
```

评测用的原始论文包、被引 PDF、item bench 的逐条结果不入库，只保存在作者本机。

## 16. 希望评审重点看的问题

1. **原则边界**：有没有任何代码路径会在没有修订标记的情况下改动原文，或者把实质性问题写成修订？
2. **证据校验**：`support/evidence.py` 为了兼容 PDF 抽取放宽了三处（连字符、空格、省略号拼接），会不会放过模型编造的证据？
3. **状态语义**：`not_found` 的判定条件是否足够保守？会不会把真实存在、只是元数据很差的文献判成不存在？
4. **评测设计**：注入点用干净稿白名单来选，是否高估了查全率？宽严两种查准率口径是否合理？下一步应该优先人工核对哪部分干净稿报警？
5. **成本与稳定性**：flash 首轮加 max 复核的级联是否合理？有没有更便宜的办法让判断更稳定？
6. **导出健壮性**：`export/writer.py` 拆分 run、整段移动参考文献的做法，在复杂 Word 文档上（域代码、修订嵌套、内容控件、文本框）会不会破坏文件？
7. **安全**：`sandbox: false` 和 CORS `*` 加 token 的组合在本地应用里够不够？token 放在查询参数里是否会经日志泄露？
8. **隐私说明**：第 8 节列出的云端数据是否完整、准确？
9. **用户负担**：一篇稿件上百条提示时，严重度分级和默认隐藏的策略是否够用？
