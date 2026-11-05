# 过夜任务进度

更新时间：2026-11-05 深夜（无人值守）

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
