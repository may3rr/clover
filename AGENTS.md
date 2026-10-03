# AGENTS.md — Clover（工作代号 citecheck）

> 本文件放在仓库根目录，是每个任务开始前必须完整阅读的项目上下文。
> 任务清单见 `PLAN.md`。本文件中的约束优先级高于任何单个任务的描述。

## 1. 产品是什么

一个 macOS 桌面应用。用户拖入一篇 `.docx` 论文，系统给出一份"引用体检报告"：

1. **真实性**：参考文献是否真实存在，作者、年份、DOI 是否对得上。
2. **支持度**：正文中"论断—引用"对，被引文献是否真的支持这个论断，并给出原文证据。
3. **分布**：引用功能（背景、方法、对比等）与各章节引用密度，和目标领域已发表论文的常态对比。
4. **规范**：引用格式不统一、参考文献未被引用、正文引用找不到对应条目、错别字等。

体检完成后，用户可以**一键导出一份新的 docx**：
- 所有问题以 **Word 批注** 的形式挂在对应位置；
- 错别字修正、参考文献重新排序以 **Word 修订（Track Changes）** 的形式写入，由用户在 Word 中逐条接受或拒绝。

用户在自己熟悉的 Word 里完成修改，这是本产品"提效"的落点。

**当前版本只支持英文论文。** 中文论文（GB/T 7714、中文文献核验、中文对标语料）作为后续工作，现有中文解析代码保留但不再扩展，界面与演示均以英文论文为准。

参赛场景：天猫 AI 黑客松，效率进化赛道，阿里云特别赛题（基于 Qwen 的科研提效）。

## 2. 不可违反的产品原则

- **机械性问题给修订，实质性问题只给批注。** 这是本产品最重要的边界：
  - 可以写成修订的（机械性）：错别字、参考文献重新排序、因重排而变化的正文引用编号。
  - 只能写成批注的（实质性）：编造或信息不符的文献、张冠李戴的引用、缺少支撑的论断、引用分布异常、引用堆砌。
  - 绝对不做的：改写、续写、生成任何论文正文；自动删除或替换任何参考文献；自动推荐"应该引用哪篇文献"。删不删、换不换，是作者的决定。
- **所有改动都必须可撤销。** 导出文件中的每一处改动都是修订，绝不静默修改原文。原文件永不覆盖，导出为新文件。
- **证据必须可追溯。** 任何"支持 / 不支持"判断都必须附带被引文献的原文片段，且该片段必须能在原文中逐字找到（见第 5.3 节）。找不到就降级为"无法判断"。
- **不确定就说不确定。** 无法核验（如中文文献查不到）必须标为"无法核验"，绝不能标为"不存在"。
- **全程使用 Qwen 系列模型。** 不接入其他厂商的大模型。
- **稿件隐私。** 全文解析在本机完成；云端只接收需要复核的"论断 + 证据片段"，不上传整篇稿件。

## 3. 技术栈

| 层 | 选型 |
| --- | --- |
| 桌面壳 | Electron，脚手架 electron-vite，TypeScript |
| 前端 | React 18 + TypeScript + Tailwind CSS（只用于布局工具类，视觉 token 走 CSS 变量） |
| 后端 | Python 3.11，FastAPI，本地服务 `127.0.0.1:8765` |
| 解析 | lxml 直接读 docx 的 XML；python-docx 仅作辅助 |
| 检索 | Crossref、OpenAlex、Semantic Scholar、arXiv 公开 API |
| 模型（云） | 阿里云百炼 DashScope，OpenAI 兼容接口，模型名全部走配置 |
| 模型（端） | mlx-lm 加载 Qwen 小模型，Apple Silicon 本地推理（可选能力，失败自动回退云端） |
| 缓存 | SQLite（检索结果、模型判断结果都缓存，避免重复花钱；另存 reports 表：体检完成的报告落库，首屏历史列表与重新导出都走它） |
| 测试 | pytest（后端），vitest（前端纯函数） |

## 4. 目录结构

```
citecheck/
├── AGENTS.md
├── PLAN.md
├── backend/
│   ├── pyproject.toml
│   ├── citecheck/
│   │   ├── config.py          # 读取 .env 与 config.toml
│   │   ├── schema.py          # Pydantic 数据模型（第 5.1 节）
│   │   ├── parse/             # docx 解析
│   │   ├── refs/              # 参考文献结构化与真实性核验
│   │   ├── support/           # 论断抽取与支持度判断
│   │   ├── distribution/      # 引用功能与分布
│   │   ├── lint/              # 规范类检查与错别字
│   │   ├── export/            # 导出带批注与修订的 docx
│   │   ├── llm/               # Qwen 客户端（云 / 端 路由）
│   │   ├── cache.py
│   │   ├── pipeline.py        # 串起四层，产出 Report
│   │   └── server.py          # FastAPI
│   ├── benchmarks/            # 领域对标数据（JSON）
│   └── tests/
│       └── fixtures/          # 测试用 docx
├── app/                       # Electron + React
│   ├── electron/
│   └── src/
│       ├── styles/tokens.css  # 唯一的设计 token 来源
│       ├── components/
│       └── screens/
└── demo/                      # 演示样例与录屏脚本
```

## 5. 核心约定

### 5.1 数据模型（schema.py）

```python
class Section:        id, title, canonical  # canonical ∈ intro|related|method|experiment|discussion|conclusion|other
class Paragraph:      id, section_id, text, char_offset
class CitationMarker: id, paragraph_id, start, end, raw, ref_ids: list[str]
class Reference:      id, raw, title, authors, year, venue, doi, lang  # lang ∈ en|zh|other
class RefCheck:       ref_id, status, matched: dict | None, issues: list[str]
                      # status ∈ verified|mismatch|not_found|unverifiable
class Claim:          id, paragraph_id, start, end, text, marker_ids
class SupportCheck:   claim_id, ref_id, label, evidence: str | None, source_kind, rationale
                      # label ∈ supported|partial|unsupported|undetermined
                      # source_kind ∈ abstract|fulltext|none
class Finding:        id, layer, severity, anchor, title, detail, refs: list[str]
                      # layer ∈ authenticity|support|distribution|norms
                      # severity ∈ high|medium|low
                      # anchor = {paragraph_id, start, end} | None
class Revision:       id, kind, anchor, old, new, reason
                      # kind ∈ typo|ref_reorder|marker_renumber
                      # anchor = {paragraph_id, start, end}
                      # 只有机械性改动才能生成 Revision（见第 2 节）
class Report:         document, sections, paragraphs, markers, references,
                      ref_checks, claims, support_checks, distribution,
                      findings, revisions
```

导出时，`findings` 全部转为批注，`revisions` 全部转为修订。

前后端共用这一套结构。前端类型从后端的 JSON Schema 生成，不手写第二份。

### 5.2 模型调用

- 所有模型调用都经过 `llm/` 模块，业务代码不直接调用 SDK。
- 模型名、base_url、温度全部来自 `config.toml`。不要在代码里写死具体模型版本号。
- 判断类任务 `temperature=0`，要求结构化 JSON 输出，并做 Pydantic 校验；校验失败重试一次，再失败记为 `undetermined`。
- 每次调用写入缓存，键为 `sha256(模型名 + prompt)`。

### 5.3 证据逐字校验

模型返回的 `evidence` 必须在被引文献原文中逐字出现。校验方式：两边都做 Unicode NFKC 归一化、压缩空白、统一引号后做子串匹配。匹配失败时，把 `label` 降级为 `undetermined`，并在 `rationale` 中记录"证据未能在原文中定位"。这是本产品可信度的核心，不允许跳过。

### 5.4 工程习惯

- 每个任务结束前运行对应的验收命令，全部通过才算完成。
- 每完成一个任务提交一次 git commit，提交信息以任务编号开头，例如 `T2: reference verification via Crossref/OpenAlex`。
- 网络请求一律设置超时与重试，并遵守各 API 的礼貌访问要求（Crossref 带 `mailto`，arXiv 请求间隔至少 3 秒）。
- 不要引入本文件未列出的大型依赖。确有必要时，先在任务说明里说明理由。

## 6. 设计规范（必须严格执行）

气质参考：Notion 的内容区 + macOS 26 的窗口壳——通高系统侧栏（原生 vibrancy）、透明底侧栏图标（Finder / Notion 风格）、安静的排版。克制、留白充足，一屏只做一件事。

### 6.1 字体

- **只用系统字体：** `font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", system-ui, sans-serif;`
  英文自动使用 SF Pro，中文自动使用苹方。禁止引入任何网络字体或自带字体文件。
- **层级只靠字重区分。** 可用字重：400、500、600、700。
- **字号六档：**
  - `13px`：次要文字——计数、说明、组标签、注释、属性行标签。
  - `15px`：界面文字（标题、按钮、标签、列表行、属性值）。
  - `17px`：阅读区论文正文（行高 `1.7`）与详情视图标题。
  - `20px`：阅读区章节标题（600，上间距 32px）。
  - `26px`：空状态 / 运行页大标题（600）。
  - `32px`：阅读视图论文标题（700，Notion 页面标题）。
- 主文字颜色 `--text`；次要信息（计数、说明、caption、组标签）用 `--text-secondary`。语义色只用于状态。
- 禁止全大写标签，禁止在标题里单独给某个词加粗或变色（语义计数除外），禁止用中点连接元信息（如 `A · B · C`），按钮文字后面不加箭头，中文标题旁不放英文小字标签。

### 6.2 颜色（`app/src/renderer/src/styles/tokens.css` 是唯一来源）

tokens.css 中允许十六进制和 rgba；组件里禁止任何颜色字面量，只能引用变量。调色板是 Notion 暖中性色：

```css
:root {
  --bg: #ffffff;  --bg-subtle: #f7f7f5;
  --text: #37352f;  --text-secondary: rgba(55,53,47,0.65);
  --accent: #2383e2;
  --fill: rgba(55,53,47,0.06);          /* hover */
  --fill-strong: rgba(55,53,47,0.09);   /* 选中行（中性灰胶囊） */
  --sidebar-tint: rgba(247,247,245,0.55); /* 侧栏可选叠色，透出 vibrancy */
  --separator: rgba(0,0,0,0.1);          /* 窗格分隔线（唯一允许的面板线） */
  --glass-edge / --glass-shadow          /* 骨架页边 / 浮层阴影 */
  /* 语义图形色 = macOS 系统色：#FF5F57 / #FEBC2E / #28C840（浅），
     #FF6961 / #FFC53D / #32D74B（深）；--*-tint 是同色 ~0.2 alpha（深 ~0.28）；
     圆点、tile、图标、勾选、进度条、spinner 都用这一组 */
  --high / --medium / --ok / --*-tint
  /* 语义文本色 = 可读变体：#D70015 / #A05A00 / #1E7E34（浅），
     深色同图形色。判定词、彩色计数用 --*-text，正文文本永不上彩色底 */
  --high-text / --medium-text / --ok-text
  --low = --text-secondary;  --low-tint = --fill-strong;
  /* 图层色相（侧栏图层图标的字形色，也用于其余 tile；非语义色相，语义色只表达状态）：
     indigo #5856D6、blue #007AFF、teal #30B0C7、purple #AF52DE、
     grey #8E8E93，dark 用深色系统色变体 */
  --tile-indigo/blue/teal/purple/grey
  /* 品牌色（设置页供应商图标，LobeHub lobe-icons 品牌色）：
     --brand-qwen / --brand-deepseek；品牌色块上的白色 glyph 用 --on-brand */
  --hairline / --shimmer                 /* SVG 页边 / 占位微光 */
  --ease: cubic-bezier(0.2, 0.8, 0.2, 1) /* 唯一缓动 */
}
/* dark：--bg #191919 等，同名定义在 tokens.css */
```

图层图标配色：文献真实性 indigo，论断支持度 blue，引用分布 teal，格式规范 purple，全部问题 grey。检查器列表行不用 tile，用严重度实心 glyph（high=红感叹号圆、medium=橙三角、low=灰 i、rev=绿铅笔），因为列表已按图层分组；真实性/支持度行的次要行写文献标识（`[1] Vaswani 等，2017，标题`），问题描述进详情。

### 6.3 不加没有意义的线条

- **禁止分割线、边框、描边、下划线装饰。** 区块之间靠留白和底色区分。唯一的例外：侧栏 / 检查器与阅读区之间各一条 `1px var(--separator)` 发丝线（用 box-shadow 画，不用 border）。
- 正文里的问题高亮用**柔和底色**（`--high-tint` 等，`padding: 0 2px; box-decoration-break: clone;`）。
- 阴影只允许 `--glass-edge` / `--glass-shadow`，用在骨架页边和浮层菜单上；窗格和普通面板不加阴影。
- 不要把内容切成一排排一模一样的圆角卡片。

### 6.4 间距、圆角、动效

- 间距只用这组值：4 / 8 / 12 / 16 / 24 / 32 / 48 px。
- 圆角：检查器内的详情卡 12px，callout 8px，列表行 8–10px，其余 tile 5px（20px 尺寸），高亮 4px，主按钮胶囊形（980px）。侧栏和检查器是通高直边窗格，没有圆角。
- 动效曲线统一 `var(--ease)`；时长：hover/press 160ms、面板 240ms、跨屏 morph 320–400ms。只允许 transform / opacity（骨架条加 scaleX）。
- 屏幕切换与列表→详情用 `document.startViewTransition`（`lib/vt.ts` 的 `morph()`，reduced-motion 时退化为直接切换）。
- 尊重 `prefers-reduced-motion`：所有动画降为仅 opacity 或直接跳过。
- 焦点环只在真实键盘焦点出现（`--accent` 2px，这是唯一允许的"线"）。不要在加载或鼠标点击后程序化 focus 元素。

### 6.5 窗口

- `titleBarStyle: 'hiddenInset'`，红绿灯融入界面；窗口 `vibrancy: 'sidebar'`。
- 报告页三窗格通高直边：左侧栏 240px（顶到窗口边缘，圆角 0，透明 / `--sidebar-tint` 透出原生 vibrancy），右检查器 380px（圆角 0，`--bg-subtle`），中间阅读区 `--bg`。窗格之间各一条 `1px var(--separator)` 发丝线。根节点透明，每个区域自己画底色。
- 截图模式需 `backgroundThrottling: false`，否则窗口被遮挡时 `screencapture` 拿到旧帧。
- 最小窗口 1100 × 720。

### 6.6 文案

- 简体中文，主动语态，动词开头。按钮写清楚会发生什么，例如"开始体检"，不写"提交"。
- 不道歉，不用感叹号，不写营销腔。
- 空状态和错误都要告诉用户下一步怎么做。例如："无法读取这个文件。请确认它是 .docx 格式，然后重新拖入。"

### 6.7 图标与插画

- 只用自绘的内联 SVG，SF Symbols 风格 **filled**（`.fill` 变体）：`fill="currentColor"`，双色处用 `var(--tile-bg)` 镂空。描边只留给 chevron 和 checkmark 的描画动画。禁止图标字体和图标库。
- 侧栏图标（图层、历史记录、检查另一篇、设置导航）用 `components/SideIcons.tsx` 的透明底实心 glyph：20×20 网格，可见区 2–18，镂空用 SVG mask 做成真孔，不画色块。图层图标字形色取图层色相（见 6.2）；其余图标用 `--text-secondary`，选中行变 `--text`。窗口失焦时色相图标降饱和（`.side-ic-hue`）。
- 其他位置（运行页、引导页、关于页）仍可用 20–22px 圆角色块（`.tile`）：白色实心 glyph + 图层色底。
- 插画（空状态纸张堆、阅读页 56px 页面图标、空筛选印章）全部内联 SVG，颜色只走 CSS 变量，viewBox + CSS 控尺寸，不用 PNG。
