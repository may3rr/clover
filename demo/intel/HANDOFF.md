# Intel 本地化交接（2026-11-05 晚 → 11-06 早）

给明天接手的 Mac 会话。先读这份，再读 `AGENTS.md` 5.5 节（两台电脑的同步规则）。

## 0. 11-06 更新

- Intel 机器夜里跑完了 T0 到 T7（`296a34b`），结论见 `demo/intel/bench/MORNING_REPORT.md` 和 `JUDGE_ACCURACY.md`。
- **判断默认走云端**（用户 11-06 决定）。本地 8B 检出 51/93 个已标注问题，云端 flash 检出 76/93。本地生成只用于隐私模式和离线兜底。
- `cn/intel` 已合并进 master，第 3 节问题 1 到 4 已修：开启批处理时本地并发自动取 `max(max_concurrency, batch_max_num_seqs)`，超时改用 `batch_timeout`（默认 120 秒），本地用量按请求记录，`batch_cache_size` 默认降到 4（英文稿峰值 18GB），`uv.lock` 纳入版本管理。
- 下一步：隐私模式与发送清单（第 6 节），然后做向量 BM25 预选（`demo/intel/bench/EMBED_PREFILTER.md`）。

## 1. 现状（11-05 晚的记录）

**仓库同步：**
- `master` = `ee8f4c3`，Mac 本地、GitHub、GitCode 三处一致。
- `cn/intel` 最后已知的提交是 `d7f0819`（11-05 21:14），**还没有合并进 master**。
- 21:14 之后到 22:50，Intel 机器没有新的推送。那时 T3 应该在跑；它是还在跑还是会话停了，还不清楚。

**两台机器：**
- Mac：主开发机。
- Intel 决赛机：HP OmniBook 7，Core Ultra 5 338H，Arc B370 核显，NPU，32GB 内存，Windows 11。
  - 模型放在 `C:\clover-models`，仓库在 `C:\clover`，分支 `intel`。
  - 机器上的 agent 只负责下载、测试模型，并按 `demo/intel/OVERNIGHT_TASKS.md` 执行过夜任务。
  - 用户负责在两台机器之间转发消息。

**SSH 连不通，暂时放弃。**
- 会场 Wi‑Fi「天猫Ai黑客松高校挑战赛」开了客户端隔离：两个方向的 TCP 都不通，Mac 这边对 `10.1.1.252` 的 ARP 也解析不出来。
- 国内网络下 Tailscale 不可用。
- Mac 的 `~/.ssh/config` 里留着 `Host win`（`10.1.1.252`，用户 `天猫AI`，主机指纹 `SHA256:TxXXhMdIxcfquyOvJkrVPE6JGs5AkYd/IRcYMMb1AZ0`）。换到不隔离的网络后可以再试，IP 可能会变。
- 两台机器之间只靠 GitCode 传结果。

## 2. 已有结论（数据都在 `demo/intel/bench/`）

| 项 | 结果 |
| --- | --- |
| 向量 0.6B int8 | CPU、GPU、NPU 都能跑。NPU 冷加载 101 秒，缓存后 0.9 秒；24 个窗口 1.6 秒 |
| 重排 0.6B int8 | GPU 上 24 个候选 0.29 秒；NPU 编译失败（Reshape 动态维度） |
| Qwen3-8B int4，GPU | 连续批处理 16 并发时 122 token/s，平均每个请求 1.05 秒；开 prefix caching 后 158 token/s；峰值 RSS 约 7 到 8GB |
| Qwen3-8B int4，GPU，质量 | 6 条小样本中 judge 6/6；extract 经过规范化后 6/6 |
| Qwen3-8B-int4-cw，NPU | 冷编译 45 秒，缓存后 5 秒；decode 18.6 token/s；judge 5/6，把"50 帧 vs 5 帧"判成了支持 |
| NPU 同时跑抽取和向量 | 两边各慢约 3 倍。结论：NPU 只跑向量 |
| Qwen3-1.7B 非对称 int4，NPU | 编译 40 分钟以上，放弃。NPU 必须用对称、逐通道量化的模型 |
| Qwen3-4B int4 | sha256 校验通过，但 OpenVINO 2026.4.1 在 CPU 和 GPU 上加载都报 Reshape 错误，放弃 |
| Qwen3.5-9B | IR 是视觉语言模型的结构，LLMPipeline 用不了，放弃 |
| Windows 前端 | 能跑完一篇（1 分 48 秒，15 个问题）。窗口宽 1300、缩放 150% 时右侧被截断 |

**推荐分工（待 T3、T4 验证）：** 核显上一个 8B 连续批处理服务所有生成任务，重排也放核显；NPU 和 CPU 一起算向量。按估算，判断约 255 次调用、约 4 到 5 分钟。向量约 6000 个窗口，是新的瓶颈，需要先用 BM25 预选。

## 3. `d7f0819` 的审查结论（尚未合并）

Intel agent 改的内容：
- `llm/ov.py`：新增 `BatchGenerator`
- `llm/local.py`：OpenVINO 引擎加入微批
- `llm/router.py`：`[llm.local].tasks`，按任务路由
- `llm/client.py`：独立的本地并发信号量
- `support/judge.py`：新增 `route` 参数
- `config.py` 和 `config.example.toml`：新增批处理参数
- 测试：修了 LaTeX 测试里的 CRLF 问题，缺私有 PDF 时自动生成空白 PDF，`pyproject` 加了 `pythonpath = ["."]`

在 Mac 上用 worktree 跑过：**486 passed，28 skipped**。

**合并前要改的：**
1. **并发上限比批大小小。** `LocalSettings.max_concurrency` 默认 8，`batch_max_num_seqs` 默认 16，所以每批最多只有 8 个请求，用不满调优得到的配置。改成 `max_concurrency >= batch_max_num_seqs`，或者开启 batching 时自动取二者中较大的那个。
2. **超时太短。** 本地超时 `timeout` 默认 20 秒，而 16 个判断请求跑一批大约要 17 秒，再加上排队就会超时。超时后回落云端，没有 Key 时会记为 undetermined。开启 batching 时把超时提到 90 到 120 秒。
3. **用量统计会错位。** `_last_usage` 是引擎级的共享变量，并发时 token 用量会记到别的请求上。应该改成按请求返回用量。本地调用不计费，优先级低。
4. **`uv.lock` 被 `.gitignore` 忽略了**，所以 Windows 装到的是最新依赖（FastAPI 0.162、Starlette 1.10）。建议把锁文件纳入版本管理。
5. **核对 T3 的数据。** 看完结果后，要检查超时和 undetermined 的数量，判断它们有没有拉低本地准确率。

## 4. 明天的步骤

1. 执行 `git fetch cn`，看 `cn/intel` 是否有 `d7f0819` 之后的提交，重点看这几份：
   - `demo/intel/bench/PROGRESS.md`
   - `demo/intel/bench/MORNING_REPORT.md`
   - `demo/intel/bench/JUDGE_ACCURACY.md`
   - `demo/intel/bench/e2e/`
2. 如果夜里停在 T3 附近：让用户在 Intel 机器上开一个新会话，读 `PROGRESS.md` 从断点继续。要提醒用户，T3 数据包的解压密码只在对话里给过，不在仓库里，要用户重新提供或在原会话里找。
3. **评估 T3。** 对比本地 8B 和云端 flash 首轮判断的基线（`demo/intel/bench/data/judge_cloud_flash_current.json`：injected 37/41，true_issue 39/52，false_alarm 233/415）。据此决定 judge 是否默认走本地，这需要用户拍板。
4. **合并 `cn/intel`。** 在 Mac 上改掉第 3 节的问题 1 和 2，跑完整测试，再按 AGENTS 5.5 推送到 GitHub 和 GitCode。
5. **下一批 Mac 开发：**
   - 向量 BM25 预选，加上 NPU 和 CPU 一起算向量（参考 T6 的方案文档，如果夜里写了）；
   - Windows 前端截断（参考 T7 的诊断，如果夜里做了）；
   - 隐私"发送清单"：报告里显示实际发到云端的字数（之前提过，用户还没确认）。
6. **产品决定：**
   - judge 是否默认走本地：等 T3 数据出来再请用户拍板。
   - **隐私模式和发送清单：用户已确认要做**，见第 6 节。
   - **路演中 NPU、GPU、CPU 怎么讲：用户授权由我们定**，见第 7 节，不用再问。

## 6. 隐私模式与发送清单（已确认要做）

**隐私模式**（设置页开关）：
- 打开后，错别字、引用功能、文献结构化、论断抽取、期刊画像都强制走本地。
- 含有"本文提出""we propose"这类表述自身贡献的论断句，改由本地判断，不发到云端。
- 云端只接收：带引用的论断句、被引文献的原文片段，以及参考文献条目（这些本来就是公开信息）。
- 题目、摘要、章节标题、图表题注都不出本机。期刊对标细化在隐私模式下走本地或关闭。
- 本地没有可用模型时，在设置页说明哪些任务会因此回落云端，或者被跳过。

**发送清单**：
- `llm_usage` 按请求记录发往云端的任务和字符数，向量和重排也要记。
- 报告里新增一处汇总，写明正文共多少字、实际发送多少字，以及发送了哪些类别：论断 N 句，被引片段 N 段，参考文献 N 条。
- 可以展开逐条查看发送的内容。
- 文案按 AGENTS 第 6.6 节写。数字以 `llm_usage` 实际记录为准，不估算。

**合并前要先修的现状：** 错别字检查现在逐段发送整篇正文；期刊画像会发送题目和摘要前 2000 字。这两处与 AGENTS 第 2 节"不上传整篇稿件"的说法冲突。隐私模式至少要把这两处挪到本地，同时要更新 AGENTS 第 2 节和引导页的隐私说明。

## 7. 路演怎么讲端侧分工（已定稿方向）

主线是"三颗芯各干所长，稿件不出本机"，不比谁跑得快：

- **NPU：常驻的检索引擎。** 被引文献切成几千个片段，算向量是一篇稿件里次数最多的 AI 运算，持续时间长、功耗敏感，正好交给低功耗的 NPU。实测 24 个片段 1.6 秒，结果与 CPU 一致。
- **GPU（Arc 核显）：判断引擎。** 一篇稿件约 200 次"论断是否被原文支持"的判断，用连续批处理一次并发 16 条，平均每条约 1 秒；吞吐是逐条跑的 5 到 6 倍。重排也放在核显上，24 个候选 0.29 秒。
- **CPU：调度与兜底。** 解析 docx 和 LaTeX、BM25 粗筛、证据逐字校验，NPU 忙时分担向量计算。
- **云端 Qwen：只在需要时出场。** 复核少量最难的判断，例如本地判为不支持、需要二次确认的那 15% 到 20%。只发送一句论断和一段原文。

要讲清楚的取舍：
- 为什么不全放 NPU：实测 NPU 同时跑生成和向量会互相拖慢约 3 倍；对称量化的 8B 在 NPU 上把"50 帧 vs 5 帧"判成了支持。所以判断这种对精度敏感的任务放在核显上。
- 为什么不全放云端：放在本地后，隐私模式下正文的发送量接近 0，只有发送清单里列出的那几样会出本机（第 6 节）。

现场可以展示：运行页上 NPU、GPU、CPU 各自在做什么，配合 Qwen 与 Intel 的标识；再打开发送清单，让评委看到稿件只发出了那几句话。

所有数字以 T3、T4 实测为准，最终写进路演 PPT 前要再核对一遍。

## 5. 相关文件

- `demo/intel/OVERNIGHT_TASKS.md`：过夜任务单，T0 到 T7
- `demo/intel/WINDOWS_AGENT_PROMPT.md`：第一轮的环境搭建和测试说明
- `demo/intel/README.md`、`design/Intel本地化移植方案.md`：早期方案
- `demo/intel/bench/data/judge_pairs.zip`：508 对标注好的判断样例，加密存放；数据来自 Mac 上的 `demo/testset/reports` 和 `reports_r1105`
- `demo/testset/judge_ab.py`：判断 A/B 的测试脚本，报出规则与 T3 一致
