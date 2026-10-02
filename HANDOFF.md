# 交接 — 引用体检（citecheck）

日期：2026-10-02。给明天继续开发的人（或我自己）看的当前状态。

## 一句话状态

后端四层管线 + Word 导出 + Electron 三屏界面全部完成并测试通过；正在进行的是收尾：解析鲁棒性补强、T11 演示论文检出率实测、打包成 .app。

## 今天做了什么

### 已完成并提交（git log 可见，T0–T12）

| 任务 | 内容 |
| --- | --- |
| T0 | 项目骨架、config.toml + .env 配置、Pydantic schema、SQLite KV 缓存 |
| T1 | docx 解析：XML 直读保偏移量、标题识别（样式表 + 编号正则兜底）、引用标记三通道（Zotero/EndNote 域代码 → 上标 → 正则）、文献表定位三路径、标记-文献链接 |
| T2 | 文献真实性核验：Crossref + OpenAlex + Semantic Scholar + arXiv 四来源；分阶段查询（前面查到的不再问 arXiv，arXiv 批量查）；`not_found` 需要 Crossref+OpenAlex+arXiv 都应答且无匹配（S2 可选）；同标题但作者年份都对不上的记录判为另一篇文献，不再误报 |
| T3 | 论断抽取 + 支持度判断：证据必须在被引文献原文中逐字定位，定位不到一律 `undetermined`；BM25 选片段、PDF 参考文献区过滤 |
| T4 | 引用分布：150 篇 arXiv cs.CL 论文做领域对标基准 |
| T5 | 规范检查：错别字、编号重排、文献重排（生成 Revision，导出为修订） |
| T6 | pipeline 编排 + FastAPI SSE 服务；分阶段核验、源熔断器、计时埋点、并发 6→12 |
| T10 | docx 导出：批注挂 findings、修订挂 revisions，LibreOffice 验证过 |
| T7–T9 | Electron 壳（hiddenInset + vibrancy + 中文菜单）、三屏（拖入/骨架检查中/三栏报告页）、Notion 式报告页、详情对照视图、键盘导航、真实窗口截图与 E2E |
| T12 | **token 用量统计**：每次真实调用和缓存命中写入 SQLite `llm_usage` 表（时间/供应商/模型/任务/输入输出 token/是否缓存），按 天+供应商+模型 聚合；查看用 `backend/scripts/usage_stats.py`（支持 `--by-task`、`--day`） |
| T14 | **账户与设置界面**：左下角头像+名字（Empty 屏和报告侧栏都有）点开设置屏——macOS 设置式左导航 + 分组卡片：账户（头像图片或姓名首字+色板，经原生图片选择器）、批注署名（导出的 Word 批注带用户自己的名字和缩写，有预览）、模型（读写 config.toml 的各任务模型 + .env 的 API Key + "拉取模型列表"）、用量与费用（llm_usage 加了 doc 列按论文聚合，按 config.py 里内置的百炼价格表估算费用）。后端新增 `/prefs`、`/usage`、`/config`、`/models` 四个端点；截图状态加了 `settings-*` 四个 |

### 模型选型（已写入 backend/config.toml）

| 任务 | 模型 | 说明 |
| --- | --- | --- |
| judge 支持度判断 | qwen3.8-flash | 主判 |
| review 复核 | qwen3.8-max | 只复核"不支持/部分支持"的结论 |
| review_fallback | qwen3.7-max | max 不可用时的兜底 |
| extract / structure / function | qwen3.7-flash | 抽取类便宜档 |
| typo | qwen3.8-flash | |
| local | 默认关闭 | mlx-lm 代码保留，换机器可开 |

实测：一次完整检查约 0.19 元。

### 界面设计现状（按用户反馈改过两轮）

- 左右栏是通高直边窗格，与正文之间各一条发丝线（唯一允许的分隔线）
- 语义色 = macOS 红绿灯色：红 #FF5F57 / 橙 #FEBC2E / 绿 #28C840（浅色），深色 #FF6961 / #FFC53D / #32D74B
- 图层 tile 用非语义色（indigo/blue/teal/purple/grey），不与严重程度冲突
- 检查器列表行用严重度实心图标；文献行次要信息显示 `[N] 作者 等，年份，标题`
- 解析时显示论文骨架图（真实章节标题 + 段落条 + 引用圆点，按完成度点亮）
- 图标全部是自绘内联 SVG，实心风格；无斜体；无英文大写标签
- 工具栏实底，滚动时下面浮现发丝线

## 正在进行（后台任务中，可能尚未提交）

1. **T1 解析鲁棒性补强**（针对"学生上传的文档格式五花八门"）：
   - 解析 `word/numbering.xml`，把 Word 自动编号还原成文本标签（修参考文献表和编号标题两个盲区）
   - 读 `word/footnotes.xml`/`endnotes.xml`，支持脚注式引用
   - 三个确定性路径都找不到文献表时，用便宜模型定位边界、程序验证后才采纳
   - 零标记零文献时报告明确说"没找到"，不出空报告
   - 新增 torture fixture 测试（自动编号文献表、脚注引用、零样式文档）
2. **T11 演示论文**：`demo/base_paper.docx` 已生成（英文 NLP 论文，20+ 篇真实 RAG/幻觉文献）。接下来 inject.py 注入 10 个已知问题（2 编造文献、1 错年份、2 张冠李戴、1 未引用、1 堆砌、3 错别字），evaluate.py 按预设规则测检出率。
3. **打包**：electron-builder 出未签名 .app，`open -a` 拖入 docx 启动分析。

## 还没做 / 明天要做

- [ ] **拿 OpenAlex API key**（免费，https://help.openalex.org/api/authentication/，要邮箱）。拿到后写进 `backend/.env` 的 `OPENALEX_API_KEY=`，重跑演示评估。**没有它，演示里 2 篇编造文献只能判"无法核验"而不是"不存在"，检出率会少 2 项。**
- [ ] T11 检出率实测跑完，确认 ≥8/10 且无 high 误报（评分规则在 evaluate.py 里，不许放松）
- [ ] 打包 .app 验证：启动、后端拉起、Dock 拖入 docx、退出无残留 uvicorn
- [ ]  Word/WPS 人工验收导出文件（PLAN.md 提交前清单要求）
- [ ] 录 2 分钟 Demo 视频（收尾镜头：Word 中接受全部修订，文献顺序编号归位）
- [ ] 项目方案文档（痛点、原则、架构、检出率实测、规划）
- [ ] Onboarding：头像/名字目前走设置屏；用户说过要把这一步挪到首次启动的 onboarding 里（参考 `/Users/jackielyu/Coding/tmall-latex/demo/onboarding.html`），**先没改逻辑**
- [ ] （已决定不做）中文文献核验——只做英文，中文列为未来工作
- [ ] （可选）S2 API key 提升 Semantic Scholar 覆盖率
- [ ] ~~（可选）token 统计的界面展示~~——已在设置屏"用量与费用"里做了（T14）

## 关键路径与命令

```bash
cd /Users/jackielyu/Coding/tmall

# 测试（用 conda claude 环境）
cd backend && /opt/anaconda3/envs/claude/bin/python -m pytest -x -q

# token 用量统计
cd backend && /opt/anaconda3/envs/claude/bin/python scripts/usage_stats.py [--by-task] [--day 2026-10-02]

# 前端
cd app && npm run typecheck && npm run build && npm run lint:design && npm run test

# 启动开发模式（Electron 拉起本地后端）
cd app && npm run dev
```

- API key 在 `backend/.env`（DASHSCOPE_API_KEY 已配好，不进 git）
- 缓存在 `~/Library/Application Support/citecheck/cache.sqlite`，llm_usage 表同库
- 截图在 `app/shots/`（gitignored）
- 设计规范以 AGENTS.md §6 为准，`lint:design` 会查违规

## 已知注意点

- **不要放松检出率评分规则**——评估跑不过就查原因，不改规则凑数
- 证据逐字校验（§5.3）是产品可信度核心，不许跳过
- 语义文本色（--high-text 等）和图形色（红绿灯色）是分开的变量，正文文本永不上彩色底
- `backend/.env` 里有真实 key，提交前确认没 stage
