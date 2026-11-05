# 过夜任务单（Intel Windows 决赛机，约 12 小时，无人值守）

> 给 Intel 机器上的 agent。目标：把"本地 Qwen 跑支持度判断"从测速推进到**能在产品里跑通，并用标注数据量出准确率**。
> 第二天早上 9 点有人来看结果。做不完没关系，按优先级往下做，每一项都留下可复查的记录。

## 无人值守的规则

1. **不能等人。** 夜里没人点 UAC、没人登录、没人回答问题。需要管理员权限、需要登录、需要做决定的事，记进 `demo/intel/bench/MORNING_REPORT.md` 的「需要人处理」一节，然后跳过，继续下一项。
2. **进度落盘。** 在 `demo/intel/bench/PROGRESS.md` 里维护任务清单：开始时写「进行中」，结束时写「完成 / 失败 / 跳过」，附上一句结果。会话中断后，新会话先读这份文件，从断点继续，已完成的不要重做。
3. **每完成一项就提交并推送：** `git push cn intel`。只在 `intel` 分支上工作，不碰 `master`，不 `--force`。
4. **本轮允许修改产品代码**（`backend/citecheck/`），只限下面列出的任务。每次改完都要跑 `uv run pytest -q`，全部通过才能提交。新代码在 Mac 上也要能跑：`openvino` 和 `openvino_genai` 只能在函数里延迟导入，测试用假对象，不依赖真实模型。
5. **时间盒。** 每项任务都标了预计时长；超过两倍还没进展，就记录卡在哪里，然后跳到下一项。
6. **资源上限。** 进程峰值 RSS 不超过 16GB，系统剩余内存低于 3GB 立即停止当前测试。不要删除 `C:\clover-models` 里的任何模型。
7. 遵守 `AGENTS.md`：第 2 节产品原则，第 5.2 节模型调用约定，第 5.5 节同步规则。

## T0 准备（20 分钟）

- **防止睡眠。** 执行 `powercfg /change standby-timeout-ac 0`、`powercfg /change hibernate-timeout-ac 0`、`powercfg /change monitor-timeout-ac 30`。如果需要管理员权限，就记进「需要人处理」，但不要停下来等。
- **同步代码：** `git fetch cn && git merge cn/master`。
- **改用锁文件安装依赖：** 去掉 venv 里临时固定的 fastapi，执行 `uv sync --extra dev --extra intel`。master 已经修好了 FastAPI 的兼容问题。
- 跑一遍 `uv run pytest -q`，记下结果。
- **LaTeX 那条测试：** 对 `tests/test_parse_latex.py::test_tables_become_cell_paragraphs` 跑 `-vv`，把完整输出写进报告。它在 Mac 上是通过的。再执行 `git ls-files --eol` 看相关 fixture 的换行符，判断是不是 CRLF 导致的偏移。能定位就修，修完同样要在 Mac 上能通过。

## T1 本地引擎支持连续批处理（3 小时，最重要的代码任务）

现状：`llm/local.py` 里的 `OpenVINOEngine` 用一个工作线程逐条调用 `ov.Generator`（`LLMPipeline`），一次只能处理一个请求。实测 `ContinuousBatchingPipeline` 在 16 并发时吞吐是逐条的 5.6 倍。

要做的事：

- 在 `llm/ov.py` 新增 `BatchGenerator`，基于 `openvino_genai.ContinuousBatchingPipeline`。参数从配置读取：`max_num_seqs`、`cache_size`、`max_num_batched_tokens`、`enable_prefix_caching`，默认值用今天调优得到的推荐值。
- **在引擎内部做微批。** 请求先进入队列，最多等 30 毫秒，或者凑满 `max_num_seqs` 条，然后在工作线程里一次性调用 `generate(prompts, configs)`，再把结果分发回各自的 `asyncio.Future`。不要求真正的流式调度，先做到"批进批出"。
- **关闭 thinking。** 用 tokenizer 的 chat template 生成 prompt 后，确认输出里没有 `<think>`。如果 `extra_context` 不生效，就照 `_RERANK_SUFFIX` 的做法，在 assistant 开头手动补上 `<think>\n\n</think>\n\n`。用真实模型验证一遍。
- 在 `LocalSettings` 里加 `batching: bool`。为 true 时用 `BatchGenerator`，为 false 时保持现有行为，默认 false。
- **测试**（`tests/test_ov.py` 或新文件）：用假的 pipeline 测微批的组批、超时、结果分发，以及单条失败不影响同批其他请求。
- 用真实 8B 在 GPU 上做一次端到端冒烟：并发调用 32 次 `client.chat_json("extract", ...)`，记录总耗时。

## T2 按任务路由到本地（1 小时）

- `[llm.local]` 增加 `tasks = ["extract"]`，默认值保持现在的行为。`llm/router.py` 改为：任务在 `tasks` 里且本地已启用时，返回 `["local", "cloud"]`。
- 本地并发要有独立的上限，不和云端的 `max_concurrency` 共用。
- 本地路由失败时回落云端，这个行为不变。没有 API Key 时，云端会失败，结果记为 `undetermined`，同样不变。
- 补上测试；更新 `config.example.toml` 的注释，写清楚 Intel 机器上推荐的 `tasks` 列表。

## T3 支持度判断的准确率：本地 vs 云端（3 到 4 小时，本轮最重要的数据）

数据：`demo/intel/bench/data/judge_pairs.zip`。这是加密的 zip，密码由用户在对话里给你，**不要把密码写进任何文件或提交**。解压到 `C:\clover-data\judge_pairs.json`，放在仓库外，**不要提交解压后的文件**（里面是被引论文的原文片段）。

- 508 对标注好的（论断，文献）配对：`want=true` 的 93 条应当报出（其中注入的张冠李戴 41 条、人工确认的真问题 52 条），`want=false` 的 415 条是人工确认的误报，不应报出。
- 每条带有 `claim`、`excerpt`、`title`、`entry`、`sentence`、`focused`、`cocited`，以及当时云端的最终结论 `cloud`。
- 云端 qwen3.8-flash 首轮判断的基线已经在 Mac 上跑好：`demo/intel/bench/data/judge_cloud_flash_current.json`，结果是 injected 37/41、true_issue 39/52、false_alarm 233/415（首轮判断偏向多报，后面还有复核）。

要做的事：

- 写 `demo/intel/bench/judge_local.py`，复用 `demo/testset/judge_ab.py` 的 `_judge` 和报出规则（`variant current`：`J._PROMPT` 加 `focused` 句），但是从 json 读取配对，并强制走本地路由。用 T2 的配置，或者直接把 `route="local"` 传进 `judge_claim`；如果它不接受 route 参数，就加一个可选参数，默认值不变。
- 依次跑这几组：
  - a. Qwen3-8B-int4-ov，GPU，批处理
  - b. Qwen3-4B-int4-ov，GPU，批处理（如果已经下好）
  - c. Qwen3-8B-int4-cw-ov，NPU（逐条跑，预计约 1 小时，排在最后）
- 每组输出与基线相同的 JSON 格式（包括 `flags`），再加上每条的耗时、JSON 失败数，以及证据逐字校验被降级的条数。
- 写 `demo/intel/bench/JUDGE_ACCURACY.md`：
  - 三组和云端基线并排对比：injected、true_issue、false_alarm 三项
  - 与云端逐条对比的一致率，以及分歧最大的 10 条样例（只写 id、want、两边的结论和理由，不贴原文片段）
  - 每对的平均耗时，以及换算到一篇 200 对时的分钟数

## T4 端到端：整条流程跑本地（2 小时）

- `config.toml` 设置：本地启用，`engine = "openvino"`，`batching = true`，`tasks` 包含 judge、review、review_fallback、extract、typo、function、structure；向量用 openvino 后端在 NPU 上跑，重排用 openvino 后端在 GPU 上跑。没有 API Key 时，云端那几项会自动降级。
- 用 `demo/run_pipeline.py` 跑两篇：
  - `demo/final/演示稿/基于深度学习的目标检测研究综述.docx`（没有文献文件夹，被引原文需要联网获取，国内可能很慢，记下实际情况）
  - `demo/final/英文演示稿/deep_residual_learning.zip`
- 每篇记录：总墙钟、各层耗时、各任务的本地调用次数和失败次数、峰值内存、报告里的问题数。然后用 `demo/final/check_final.py <报告> [demo/final/injections_en.json]` 打分。
- 报告 JSON 放在 `demo/intel/bench/e2e/`，单个文件超过 10MB 就不提交，只提交打分和日志摘要。

## T5 调优测速（GPU 有空闲时随时插空跑，或者与 T1、T2 的编码并行）

- **连续批处理调优。** cache_size 取 2、4、6，max_num_seqs 取 8、12、16，交叉测试；另外测 prefix caching 开和关。在峰值 RSS 不超过 10GB 的条件下推荐一组配置。
- **向量吞吐。** 6000 个窗口，批大小取 8、24、64，分别测 NPU、CPU、GPU；再测 NPU 和 CPU 各算一半同时跑；最后在 GPU 跑 judge 批处理的同时再测一次。
- **Qwen3-4B。** 下载完成后跑 probe、batch_test 和 quality_test。
- Qwen3.5 放弃，不要再测。

## T6 （有余力再做）向量预选的方案

在 Mac 上实测，一篇演示稿约 6000 个窗口要算向量，这在本地是新的瓶颈。读 `backend/citecheck/support/` 里的检索代码，写一份方案 `demo/intel/bench/EMBED_PREFILTER.md`：在哪一步先用 BM25 为每条论断选 top-k 窗口、只给这些窗口算向量；预计能少算多少窗口；对召回可能有什么影响。可以用 T4 的日志做估算。**只写方案，不改代码**，这部分我们在 Mac 上实现。

## T7 （有余力再做）Windows 前端截断

截图显示：窗口宽 1300、缩放 150% 时，首页标题、设置页和报告页的右侧被截断。找到原因，看是窗口尺寸、最小宽度，还是某个固定宽度的 CSS。

- 如果能用很小的改动修好，就在 `intel` 分支上改，遵守 `AGENTS.md` 第 6 节的设计规范；改完跑 `npm run lint:design` 和类型检查，再截图对比。
- 改动较大的，只写原因和方案。

## 收尾：MORNING_REPORT.md（无论做到哪里，最后都要写）

- 每项任务的状态和一句话结果
- 最重要的三组数字：本地 judge 的准确率与云端对比；单篇端到端耗时；推荐配置
- 失败项和报错原文
- 「需要人处理」：需要权限、登录或决定的事项
- 改动过的产品代码文件清单，以及对应的测试结果

最后执行 `git push cn intel`。
