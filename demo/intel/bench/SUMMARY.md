# Intel Windows 机器验证汇总

- 机器：HP OmniBook 7 Laptop 16-bh0xxx
- CPU：Intel Core Ultra 5 338H（12 核）
- GPU：Intel Arc B370（iGPU）
- NPU：Intel AI Boost，驱动 32.0.100.4512
- 内存：32 GB LPDDR5X-8533
- 系统：Windows 11 家庭中文版 26200，2560×1600 @150%
- OpenVINO 2026.4.1 / openvino-genai 2026.4.1.0 / Python 3.11.18

## 1. 模型下载

| 模型 | 大小 | 状态 |
| --- | ---: | --- |
| Qwen3-Embedding-0.6B-int8-ov | 613 MB | 完成，sha256 与 HF LFS 一致 |
| Qwen3-Reranker-0.6B-int8-ov | 595 MB | 完成，sha256 与 HF LFS 一致 |
| Qwen3-1.7B-int4-ov | 1152 MB | 完成，sha256 与 HF LFS 一致 |
| Qwen3-8B-int4-ov | 4.66 GB | 完成，sha256 一致 |
| Qwen3-8B-int4-cw-ov | 4.53 GB | 完成，sha256 与 HF LFS 一致 |
| Qwen3-4B-int4-ov | 2.16 GB | 下载中（hf-mirror，速度很慢） |
| Qwen3.5-9B-int4-ov | 5.85 GB | 下载中 |
| Qwen3.5-4B-int4-ov | 3.33 GB | 排队 |

Qwen3.5 的 0.8B / 2B 未下载；全部 Qwen3.5 仓库与大小见 `ov_models.json`。

## 2. probe 基线

| 任务 | 设备 | 能否加载 | 冷加载 | 缓存后加载 | 单次推理 |
| --- | --- | --- | ---: | ---: | --- |
| Embedding | CPU | ✅ | 2.94 s | 0.84 s | 24 窗口 1.24 s；3 查询 0.15 s |
| Embedding | GPU | ✅ | 8.80 s | 1.06 s | 24 窗口 0.96 s；3 查询 0.45 s |
| Embedding | NPU | ✅ | 101.02 s | 0.87 s | 24 窗口 1.58 s；3 查询 0.18 s |
| Reranker | CPU | ✅ | 3.15 s | — | 6 候选 1.62 s；24 候选 5.93 s |
| Reranker | GPU | ✅ | 9.57 s | — | 6 候选 0.22 s；24 候选 0.29 s |
| Reranker | NPU | ❌ | — | — | Reshape 动态边界不支持 |
| 1.7B 抽取 | CPU | ✅ | 3.03 s | — | 6.10 / 3.20 s，JSON 均可解析 |
| 1.7B 抽取 | GPU | ✅ | 10.41 s | — | 3.71 / 3.19 s，JSON 均可解析 |
| 1.7B 抽取 | NPU | ❌ | 超时 300 s | — | 非对称 int4，编译 40+ 分钟未完成 |
| 8B 抽取 | GPU | ✅ | 18.7 s | — | 2.31 / 2.58 s，JSON 均可解析 |
| 8B 抽取 | CPU | ✅ | 8.9 s | — | 13.67 / 6.16 s，JSON 均可解析 |

- Embedding 三设备的 top-1 检索结果都与预期一致。
- Reranker NPU 报错：`Reshape node ... expected exactly 1 dynamic output bound dimension, got 2`。
- 1.7B 是**非对称、按组量化**的 int4，NPU 不适用；NPU 改用对称逐通道的 `-cw-` 版本。

## 3. GPU 8B 并发与质量

### 3.1 连续批处理（`batch_test.py`）

- `ContinuousBatchingPipeline`，GPU，8B-int4，prompt 1315 token，128 new token，贪心，`ignore_eos=True`。
- `max_num_seqs=16`、`max_num_batched_tokens=32768`、`cache_size=8`，关闭 prefix caching。

| 并发 | 总耗时 | 平均每请求 | 总吞吐 | 峰值 RSS | 最低可用内存 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 8.53 s | 8.53 s | 15.0 tok/s | 13.11 GB | 5.95 GB |
| 4 | 8.70 s | 2.18 s | 58.8 tok/s | 13.59 GB | 5.52 GB |
| 8 | 11.61 s | 1.45 s | 88.2 tok/s | 14.36 GB | 4.88 GB |
| 16 | 17.60 s | 1.10 s | 116.3 tok/s | 15.60 GB | 3.83 GB |
| 逐个 × 8（LLMPipeline） | 49.22 s | 6.15 s | 20.8 tok/s | 5.33 GB | 14.43 GB |

- 16 并发吞吐是逐个跑的 5.6 倍；单请求延迟从 8.53 s 降到 1.10 s。
- 峰值 RSS 高来自 `cache_size=8` 的 KV 预分配；逐个跑只有 5.3 GB。

### 3.2 真实 prompt 质量（`quality_test.py`）

| 指标 | 结果 |
| --- | --- |
| judge label 正确 | 6 / 6 |
| off_topic 标志正确 | 4 / 6（两条张冠李戴判了 unsupported，但 `off_topic=false`） |
| extract JSON + schema | 6 / 6 |
| extract 逐字子串 | 3 / 6 |
| extract 规范化后子串 | 6 / 6 |
| `<think>` 泄漏 | 0 |

- 3 条逐字失败都是标记删除后的双空格，用 `evidence.normalize_text` 后全部匹配，不是语义错误。
- judge 延迟 3.92–5.90 s，extract 2.35–3.31 s。

## 4. NPU 8B-cw

| 项 | 结果 |
| --- | --- |
| 冷编译（MAX_PROMPT_LEN=2048，空缓存） | 45.33 s |
| 缓存后加载 | 5.12 s |
| 生成：1315 token 输入 / 128 token 输出 | TTFT 2.73 s，decode 18.55 tok/s，总 9.63 s |
| `<think>` | 无（用 `ChatHistory.set_extra_context`） |
| MAX_PROMPT_LEN=4096 | 测试中 |

- 对比：1.7B 非对称 int4 在 NPU 上编译 40+ 分钟未完成；8B 对称逐通道 int4 45 秒编译完成，说明瓶颈是量化格式，不是 NPU。
- NPU 生成速度约为 GPU 连续批处理 1 并发（15 tok/s）的 1.2 倍，但远低于 GPU 16 并发（116 tok/s）。

## 5. Windows 前端

- `npm ci` 80 s；Electron 二进制需手动 `node node_modules/electron/install.js`（241 s）。
- `npm run dev` 启动成功，窗口标题 `Clover`；后端 `/health`、`/prefs`、`/reports`、`/venues`、`/benchmarks` 均 200。
- 完成引导后可拖入 docx：示例稿 `clover-sample.docx` 解析为 55 条参考文献、125 处引用，检查 1 分 48 秒，报告 15 个问题（文献真实性 5、论断支持度 2、引用分布 8、格式规范 0）。
- 无 API Key 时后端反复 `llm cloud route failed for task judge: OpenAIError`，支持度层降级，符合预期。

### Windows 上观察到的问题

1. 首次启动窗口 1294×829，首页大标题右侧被截断；加宽后完整显示（`screenshots/01-home.png`）。
2. 设置页、报告页在 1300 宽窗口下右侧内容被截断，报告页「导出」按钮只露出一部分（`screenshots/16-final-before-stop.png`）。
3. 隐私页文案仍是「一切留在**这台 Mac** 上」（`screenshots/12-consent-checked.png`）。
4. `npm ci` 不自动下载 Electron 二进制。
5. 无 API Key 时检查结果中「原文比对」0 组找到证据。

截图目录：`screenshots/`。

## 6. 待完成

- NPU 8B-cw：MAX_PROMPT_LEN=4096 结果、judge/extract 质量、组合负载。
- 4B / Qwen3.5-9B / Qwen3.5-4B 的 probe、批量与质量。
- 单篇耗时估算与最终结论。

详细命令与偏差记录见 `LOG.md`。
