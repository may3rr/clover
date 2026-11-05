# 早间报告（过夜任务）

生成时间：2026-11-06 凌晨（无人值守）

## 一、任务状态

| 任务 | 状态 | 一句话结果 |
| --- | --- | --- |
| T0 准备 | 完成 | 防睡眠；同步 `ee8f4c3`；uv sync；pytest 506 passed / 8 skipped；LaTeX 与缺 PDF 两项修复 |
| T1 本地连续批处理 | 完成 | `BatchGenerator` + 30 ms 微批；32 并发本地 extract 13.98 s，32/32 成功 |
| T2 按任务路由 | 完成 | `[llm.local].tasks`、独立本地并发上限、测试与示例配置 |
| T3 judge 准确率 | 进行中 | 8B GPU 与 4B 已跑；NPU 组待跑 |
| T4 端到端本地流程 | 未开始 | |
| T5 调优测速 | 进行中 | 批处理调优完成；向量吞吐进行中；4B 加载失败 |
| T6 向量预选方案 | 完成 | `EMBED_PREFILTER.md` |
| T7 Windows 前端截断 | 未开始 | |

## 二、最重要的三组数字

1. **本地 judge vs 云端**：
   - 云端 flash 首轮：injected 37/41，true_issue 39/52，false_alarm 233/415。
   - 本地 8B GPU：injected 27/41，true_issue 24/52，false_alarm 127/415；与云端逐条一致 311/500（62.2%）。
   - 120 条证据降级（evidence 未能在原文逐字定位）是召回损失的主要来源。
2. **单篇端到端耗时**：待 T4。
3. **推荐配置**：GPU 连续批处理 cache_size=6、max_num_seqs=16、max_num_batched_tokens=32768、prefix caching=True；16 并发 122 tok/s（共享前缀 158 tok/s），RSS 约 8 GB。
   向量：NPU 16.1 窗口/s（batch=1），GPU 84 窗口/s，CPU 1.6 窗口/s；NPU 单独或按 9:1 与 CPU 分工，GPU 忙时 judge 仍有 151 tok/s。

## 二点五、向量吞吐（231–249 token/窗口）

| 设备/组合 | 规模 | 结果 |
| --- | ---: | ---: |
| NPU batch=1 | 6000 | 373 s，16.1 窗口/s |
| NPU batch 8/24/64 | — | 编译器 LLVM abort，不支持 |
| GPU batch 8/24/64 | 6000 | 71.6 / 70.8 / 72.5 s，83.7 / 84.8 / 82.8 窗口/s |
| CPU batch 8/24/64 | 600 采样 | 385 / 357 / 389 s，1.6 / 1.7 / 1.5 窗口/s（6000 外推约 59–66 分钟） |
| NPU+CPU 各半 | 600 采样 | 180.9 s，3.3 窗口/s（CPU 瓶颈；NPU 19 s 完成） |
| GPU 8B judge 忙时 + NPU/CPU 向量 | 600 采样 | 189.6 s，3.2 窗口/s；GPU 151 tok/s，NPU 13.2，CPU 1.6 |

## 二点六、T4 端到端（本地全流程）

| 稿件 | 墙钟 | 本地调用 | 云端 | 问题数 | 峰值 RSS | 最低可用 | 注入检出 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 中文 docx | 533.2 s | 363 | 0 | 53 | 14.02 GB | 6.4 GB | 14 / 17 |
| 英文 LaTeX zip | 736.0 s | 536 | 0 | 89 | **18.07 GB** | **2.61 GB** | 12 / 16 |

- 所有 LLM 任务都走本地（judge/review/review_fallback/extract/typo/function/structure）；云端 0 次。
- 英文稿超过 16 GB 峰值上限、最低可用内存低于 3 GB 停止线，需要在 support 层降并发或把 `batch_cache_size` 降到 2–4。
- 网络是主要耗时：arXiv PDF 多次 20 s 超时回落到摘要，arXiv API 429，crossref/s2 后期限流跳过。
- 打分：中文 14/17，英文 12/16。

## 二点七、T7 Windows 前端截断（仅分析，未改）

- 首页标题字体是 `'Hoefler Text', 'Iowan Old Style', 'Palatino', Georgia, serif`，前三个是 macOS 自带字体，Windows 回落到 Georgia；`ShuffleTitle` 在挂载时按当前字体的 `getBoundingClientRect()` 把每个字母宽度锁成 em。Windows 的 Georgia 与 macOS 字形宽度不同，标题整行可能超出 1280 宽的窗口，而 `.onboard-stage` 没有水平回退/换行。
- 设置页/报告页是固定 240px 侧栏 + 380px 右侧栏的布局；在 150% 缩放下窗口有效 CSS 宽度变化时，右侧栏与主内容会一起被裁切。
- 建议（Mac 侧处理）：给标题容器加 `max-width: 100%` + `overflow-wrap: anywhere`，或用 `ResizeObserver`/`clamp()` 按容器宽度缩放；侧栏改为可折叠或 `minmax()` 栅格。

## 三、失败项与报错原文

- Qwen3-4B-int4-ov（sha256 正确）在 CPU/GPU 都加载失败：
  `Output pattern dim[1] has invalid bounds: -3891109803858067456,...`（Reshape_295，OpenVINO 2026.4.1）。
- Qwen3.5-9B/4B 放弃：LLMPipeline 报 `Port for tensor name input_ids was not found`；VLMPipeline 可加载但关不掉 thinking。
- NPU TextEmbeddingPipeline batch>1 直接 LLVM abort：
  `LLVM ERROR: Failed to infer result type(s): "IE.Add"(tensor<1x128x512x512xf32>, tensor<1x64x512x512xf32>)`。
- NPU 1.7B 非对称 int4 编译 40+ 分钟未完成（已记录超时）。

## 四、需要人处理

- 无（或：待补）。

## 五、改动过的产品代码

| 文件 | 改动 | 测试 |
| --- | --- | --- |
| `backend/citecheck/llm/ov.py` | 新增 `BatchGenerator` | `tests/test_ov.py` |
| `backend/citecheck/llm/local.py` | 微批队列、超时、结果分发 | 同上 |
| `backend/citecheck/llm/client.py` | 本地独立并发上限 | 同上 + 路由测试 |
| `backend/citecheck/llm/router.py` | `tasks` 列表路由 | 同上 |
| `backend/citecheck/config.py` | LocalSettings 新字段 | 同上 |
| `backend/citecheck/support/judge.py` | `route` 参数 | T3 |
| `backend/pyproject.toml` | pytest `pythonpath` | 全量 pytest |
| `backend/tests/test_parse_latex.py` | CRLF 读取修复 | 单测 |
| `backend/tests/test_pipeline.py` | 缺 PDF 时生成占位 PDF | 单测 |

全量测试：**506 passed, 8 skipped**。
