# 过夜任务进度

更新时间：2026-11-06（Mac 新代码 Windows 回归）

| 任务 | 状态 | 摘要 |
| --- | --- | --- |
| T0 准备 | 完成 | 防睡眠；同步到 `ee8f4c3`；uv sync；pytest 502 passed / 8 skipped；LaTeX 与缺 PDF 两项已修 |
| T1 本地连续批处理 | 完成 | `BatchGenerator` + 微批；测试通过；32 并发本地 chat_json 13.98 s，32/32 成功 |
| T2 按任务路由 | 完成 | `[llm.local].tasks`、独立本地并发上限、测试与示例配置 |
| T3 judge 准确率 | 进行中 | 8B GPU / 4B 已完成；NPU 分层采样 150 条进行中 |
| T4 端到端本地流程 | 完成 | 中文 533 s / 检出 14/17；英文 736 s / 检出 12/16；英文峰值 18 GB 超限 |
| T5 调优测速 | 完成 | 批处理/向量/Qwen-4B 全部有结果；4B 加载失败 |
| T6 向量预选方案 | 完成 | `EMBED_PREFILTER.md` |
| T7 Windows 前端截断 | 完成（分析） | 字体回落 + 固定栏宽；方案写入晨报，未改代码 |
| 收尾 MORNING_REPORT | 未开始 | |

## 11-06 Mac 新代码回归（Windows）

### 同步与依赖

- `intel` 从 `296a34b` fast-forward 到 `a4cb665`，无冲突。本地未跟踪的 `backend/uv.lock` 先移到 `%TEMP%\uv.lock.bak`，合并后改用仓库里的锁文件。
- `uv sync --extra dev --extra intel --frozen` 通过。锁文件把依赖固定到 FastAPI 0.142.2 / Starlette 1.7.0 / pydantic 2.13.5；`citecheck.server` 可导入，`/health` 返回 `{"ok":true}`，lifespan 写法在 0.142.2 下正常。
- 注意：本机 uv 配置了清华源，`uv run pytest` 会按源重写 `uv.lock` 里的包 URL（版本不变，revision 从 3 变 5）。提交前已 `git checkout -- backend/uv.lock` 还原；以后在本机跑测试用 `uv run --frozen pytest`。
- `uv run pytest -q`：**508 passed, 8 skipped**，用时 5:00。
  - 与 Mac 的 513/3 差 5 条：`tests/test_export.py:241` 有 5 条因本机没有 LibreOffice 跳过。
  - 另外 3 条 `test_real_zh.py` 因 `CLOVER_ZH_PAPER` / `CLOVER_ZH_LIBRARY` 未设跳过。总数 516 与 Mac 一致。

### 配置核对

- 本机没有 `backend/config.toml`，也没有 `%APPDATA%\Clover\config.toml`，应用回退到 `backend/config.example.toml`。example 里已经是 `batch_cache_size = 4.0`、`batch_timeout = 120`、`tasks = ["extract"]`，没有 judge / review / review_fallback。
- 仓库外 `C:\clover-data\e2e\config.toml` 原来写死 `batch_cache_size = 6.0`，且 tasks 含 judge / review / review_fallback；已改成 4.0 并移除这三项，补 `batch_timeout = 120`。
- 代码核对：开批处理时 `OpenVINOEngine.timeout = settings.batch_timeout`（`local.py`）；本地并发取 `max(max_concurrency, batch_max_num_seqs)`（`config.py` 的 `effective_concurrency()`）；`tests/test_ov.py` 覆盖超时、并发和按请求用量。

### 界面检查

截图在 `demo/intel/shots-1106/`。右上角颜色用 PowerShell `System.Drawing` 取像素。

| 状态 | 截图 | 右上角像素 | 期望 | 结果 |
| --- | --- | --- | --- | --- |
| 报告页，检查器展开，浅色 | `01-light-report-inspector-open.png` | `#f7f7f5` | 等于检查器底色 | ✅ |
| 报告页，检查器收起，浅色 | `02-light-report-inspector-closed.png` | `#ffffff` | 白色 | ✅ |
| 报告页，左侧栏收起，浅色 | `03-light-report-left-collapsed.png` | `#ffffff` | 白色 | ✅ |
| 首页，浅色 | `04-light-home.png` | `#f7f7f5` | 白色 | ❌ |
| 设置页，浅色 | `05-light-settings.png` | `#ffffff` | 白色 | ✅ |
| 运行页，浅色 | `06-light-running.png` | `#ffffff` | 白色 | ✅ |
| 引导页，浅色 | `07-light-onboarding.png` | `#ffffff` | 白色 | ✅ |
| 引导页，深色 | `08-dark-onboarding.png` | `#191919` | `--bg` | ✅ |
| 首页，深色 | `09-dark-home.png` | `#202020` | `--bg`（#191919） | ❌ |
| 报告页，检查器展开，深色 | `10-dark-report-inspector-open.png` | `#202020` | 等于检查器 `--bg-subtle` | ✅ |
| 报告页，检查器收起，深色 | `11-dark-report-inspector-closed.png` | `#191919` | `--bg` | ✅ |
| 设置页，深色 | `12-dark-settings.png` | `#191919` | `--bg` | ✅ |
| 运行页，深色 | `13-dark-running.png` | `#191919` | `--bg` | ✅ |

- **首页（空态）不达标**：右上角跟随的是右侧 inspector 占位栏的 `--bg-subtle`（浅色 `#f7f7f5`、深色 `#202020`），不是 `--bg`。要按预期变成白/`#191919`，需要让空态 inspector 顶部 52px 用 `--bg`，或让 caption 探测跳过空态 inspector。其余页面和深浅色切换都即时生效。
- **侧栏收起按钮**：`01`（左侧栏展开）和 `03`（收起后）里按钮字形 bbox 都是 `x=33..41, y=22..29`，位置完全一致；win32 下 `.side-head` 的 `padding-left: 24px` 生效，不再给红绿灯留 84px。
- **运行页动画**：标题左侧 48px 的 Qwen→Intel 动画正常；两帧对比 logo 区域有 1713 个像素不同（进度 71%→75%），确认在循环播放。`13` 是深色下的同一动画。
- **引导页大标题 150%**：浅色 `07`、深色 `08` 都完整显示 “the last mile of the paper”，没有截断；上次 `screenshots/01-home.png` 的截断这次没有复现。

### 新发现（不在清单里）

1. **运行页标题在 Windows 显示完整路径**：`App.tsx` 用 `path.split('/').pop()` 取文件名，Windows 反斜杠不分割。`06`/`13` 里标题是 `C:\clover\app\site\public\samples\clover-sample.docx`；真实拖入同样是 Windows 路径，也会显示全路径。改成 `split(/[\\/]/)` 即可。
2. **首页“选择文件”在 Windows 打开的是“选择文件夹”对话框**：主进程的 `showOpenDialog` 同时带 `openFile` 和 `openDirectory`，Windows 变成文件夹模式。在“文件夹:”框里输入 `.docx` 报“文件夹名无效”，进入含 3 个 docx 的目录后列表仍显示“没有与搜索条件匹配的项”，即单篇 docx 无法通过该按钮选择。拖入和命令行打开不受影响。建议 Windows 上拆成“选择文件 / 选择文件夹”两个入口。
3. 运行页截图用的是内置 `CITECHECK_E2E` 入口（直接调 `analyze`）。正常拖入传的也是 Windows 路径，所以第 1 条在真实拖入下同样会出现；动画本身与拖入走同一套 UI。

### ff056a3 四项确认（重启后实测）

- `intel`（`943d8c0`）合并 `cn/master` `ff056a3`，生成 `d11d499`，无冲突。
- **1 ✅ 文件对话框**：首页“选择文件”现在弹出 Windows“打开”对话框，有 `文件名(N):` 和 `论文` 类型；输入 `C:\clover\app\site\public\samples\clover-sample.docx` 后能直接选中并开始解析。截图 `17-light-file-dialog.png`。代码按平台分叉：Windows 只开 `openFile`，macOS 仍允许文件或目录。
- **2 ✅ 运行页标题**：只显示 `clover-sample.docx`，不再带路径。截图 `14-light-running-filename.png`。`baseName()` 已按 `[\\/]` 分割，`accept` / `library` / `ExportDone` 都统一用它。
- **3 ✅ 展开按钮位置**：收起检查器后，导出胶囊实际像素 `x=965..1098`，展开图标 `x=1119..1128`，三者窗口按钮字形分别在 `x=1160..1169 / 1206..1215 / 1252..1261`；`--win-caption: 144px` 把按钮盒右缘限制在约 1136，未进入 1142 起的 caption 区。点击 `(1124,27)` 能重新展开检查器。截图 `15-light-report-expand-button.png`。
- **4 ✅ 导出提示**：显示 `clover-sample（Clover）.docx`、`保存在「samples」文件夹，共 18 条批注`，文件夹名正常，没有反斜杠或完整路径。截图 `16-light-export-done.png`。鼠标点击导出胶囊中心 `(808,26)` 也能触发，不必用 `Ctrl+E`。
- **仍遗留（小）**：导出提示的第二个按钮写死为「在访达中显示」（`ExportDone.tsx:95/107`），Windows 上应为「在资源管理器中显示」。不影响本次四项。
- 清理：导出产生的 `clover-sample（Clover）.docx` 已被 `.gitignore` 忽略，测试后删除；应用与后端进程已退出。

收尾：`prefs.onboarded` 已恢复为 true；Electron 与后端进程已退出。

## T0

- `powercfg`：AC 待机/休眠 0，显示器 30 分钟。
- `git fetch cn && git merge cn/master` → `ee8f4c3`。
- 无 `uv.lock`，`uv sync --extra dev --extra intel` 解析 71 个包（FastAPI 0.162 / Starlette 1.10）。
- LaTeX 测试失败为 CRLF 偏移：测试 `write_text()` 生成 CRLF，解析器按原始字节保留 CRLF，测试 `read_text()` 归一化后偏移错位。测试读回改为 `read_bytes().decode("utf-8")`。
- `test_pipeline` 缺私有 PDF：不存在时用 pypdf 生成空白 PDF。
- `uv run pytest` 不把 backend 根加入 `sys.path`，`tests.fixtures` 导入失败；在 `pyproject.toml` 加 `pythonpath = ["."]`。
- pytest：**502 passed, 8 skipped**（修复前 500/2/8）。

## T1

- `ov.BatchGenerator`：`ContinuousBatchingPipeline`，参数默认 cache_size=6、max_num_seqs=16、max_num_batched_tokens=32768、prefix caching=True。
- `OpenVINOEngine` 微批：队列最多等 30 ms 或凑满 max_num_seqs，一次 `generate(prompts, configs)`，结果分发到各 asyncio Future；batch 失败只影响该批，单条 JSON 失败只回 None。
- 关闭 thinking：tokenizer 的 `enable_thinking=False`，若模板不认则在 assistant 开头补 `<think>\n\n</think>\n\n`。
- `LocalSettings.batching`（默认 false）与 batch_* 参数。
- 测试：组批、超时、单条失败隔离、路由 tasks（`tests/test_ov.py`）。
- 真实 8B GPU 冒烟：32 并发 `chat_json("extract")`，**13.98 s，32/32 成功，平均 0.44 s/请求，全部 local**（逐条约 80 s）。

## T2

- `LocalSettings.tasks` 默认 `["extract"]`，`route_order` 改为 `task in tasks`。
- 本地并发独立：`client._get_local_sem()`，上限 `[llm.local].max_concurrency`（默认 8），不与云端共用。
- `config.example.toml` 增加 batching/tasks/max_concurrency 注释与 Intel 推荐值。
- 路由测试覆盖 extract/judge/typo 与 enabled=false。

## T5

- 连续批处理调优（8B-int4，GPU，16 请求 × 1315/128）：
  - cache_size=2/4/6 × max_num_seqs=8/12/16 全部成功，峰值 RSS 约 8 GB。
  - 最好 cache_size=6、max_num_seqs=16 → 122.4 tok/s，1.05 s/请求。
  - prefix caching=True（共享 600 token 前缀）→ 157.6 tok/s，RSS 6.99 GB（+29%）。
  - 推荐：cache_size=6、max_num_seqs=16、max_num_batched_tokens=32768、prefix caching=True。
- Qwen3-4B：sha256 通过，但 CPU/GPU 加载均报 Reshape 动态边界错误（OpenVINO 2026.4.1），无法跑 batch/quality。
- 向量吞吐（窗口 231–249 token）：
  - GPU 6000 窗口：batch 8/24/64 = 83.7 / 84.8 / 82.8 窗口/s（约 71–72 s）。
  - CPU 600 窗口采样：1.6 / 1.7 / 1.5 窗口/s；外推 6000 ≈ 59–66 分钟。
  - NPU 6000 窗口（batch=1）：16.1 窗口/s，373 s；batch 8/24/64 编译器直接 abort（LLVM ERROR）。
  - NPU+CPU 各半（600 采样）：合计 3.3 窗口/s；CPU 是瓶颈（1.7），NPU 19 s 就做完自己那份（15.6）。
  - GPU 跑 8B judge（16 并发）同时 NPU+CPU 向量（600 采样）：合计 3.2 窗口/s；GPU 151 tok/s，NPU 13.2，CPU 1.6。
- 结论：向量瓶颈在 CPU；NPU 足够快（16 窗口/s），分工时应按速度比例分配（NPU 约 9 份、CPU 1 份），GPU 空闲时可承担向量。
- 向量脚本：`vector_bench.py`（每个组合独立子进程，NPU batch>1 崩溃可隔离）。
