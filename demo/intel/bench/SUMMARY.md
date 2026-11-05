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
| MAX_PROMPT_LEN=4096 | 冷编译 53.9 s，缓存后 4.74 s，编译通过 |

### NPU 与 GPU 质量对比（8B）

| 指标 | GPU 8B-int4 | NPU 8B-cw |
| --- | ---: | ---: |
| judge label 正确 | 6 / 6 | 5 / 6 |
| off_topic 标志正确 | 4 / 6 | 4 / 6 |
| extract JSON + schema | 6 / 6 | 6 / 6 |
| extract 规范化后子串 | 6 / 6 | 4 / 6 |
| `<think>` 泄漏 | 0 | 0 |

- NPU 的 judge 把“50 fps” vs 原文“5 fps”判成 supported；extract 有两条 claim 不连续（一条跨标记丢逗号，一条把并列结构拆成两条）。
- NPU 单次 judge 5.28–7.35 s、extract 3.47–5.31 s；GPU 分别 3.92–5.90 s、2.35–3.31 s。
- 冷编译 45 秒完成说明 NPU 本身可用；速度与精度都不如 GPU，适合跑 extract/向量，不适合单独扛 judge。

### 组合负载（180 s）

| 任务 | 单独 | 组合 | 变慢 |
| --- | ---: | ---: | ---: |
| GPU 8B judge | 4.26 s/次 | 6.08 s/次 | 1.42× |
| NPU extract | 4.13 s/次 | 12.97 s/次 | 3.14× |
| NPU 向量（24 窗口） | 1.55 s/批 | 5.06 s/批 | 3.26× |

- 峰值 RSS 11.76 GB，最低可用内存 7.41 GB；前/后半段速率基本一致，无热降频。
- NPU 的 extract 和向量共用同一设备，互相拖慢约 3 倍；GPU judge 只慢 42%。
- 组合脚本中的 solo embed 段被已加载的 NPU 大模型拖慢，干净基线由 `embed_solo_test.py` 单独测得 1.55 s/批。

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

## 6. 连续批处理调优（T5）

8B-int4，GPU，16 请求 × 1315 token 输入 / 128 token 输出，`ignore_eos=True`：

| cache_size | max_num_seqs | 吞吐 | 平均每请求 | 峰值 RSS | 最低可用 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 8 | 113.7 tok/s | 1.13 s | 7.92 GB | 11.68 GB |
| 2 | 16 | 116.4 tok/s | 1.10 s | 7.96 GB | 11.41 GB |
| 4 | 16 | 119.5 tok/s | 1.07 s | 7.98 GB | 12.27 GB |
| 6 | 16 | 122.4 tok/s | 1.05 s | 8.02 GB | 12.32 GB |
| 6 + prefix caching | 16 | **157.6 tok/s** | — | 6.99 GB | 13.19 GB |

推荐：**cache_size=6、max_num_seqs=16、max_num_batched_tokens=32768、prefix caching=True**。共享 600 token 前缀时快 29%。

## 7. 向量吞吐（6000 窗口，231–249 token）

| 设备/组合 | 规模 | 总耗时 | 窗口/s |
| --- | ---: | ---: | ---: |
| NPU batch=1 | 6000 | 373.0 s | 16.1 |
| NPU batch 8/24/64 | — | 编译器 LLVM abort | 不支持 |
| GPU batch 8 / 24 / 64 | 6000 | 71.6 / 70.8 / 72.5 s | 83.7 / 84.8 / 82.8 |
| CPU batch 8 / 24 / 64 | 600 采样 | 385 / 357 / 389 s | 1.6 / 1.7 / 1.5 |
| NPU+CPU 各半 | 600 采样 | 180.9 s | 3.3 |
| GPU 8B judge 忙时 + NPU/CPU | 600 采样 | 189.6 s | 3.2（GPU judge 151 tok/s） |

- CPU 是向量瓶颈；NPU 单个批次 19 s 就完成自己的一半。分工应按速度比例，不要把窗口平均分给 CPU。
- GPU 空闲时向量最快（84 窗口/s），但 GPU 要优先给 8B judge。

## 8. 推荐配置与单篇估算

- **生成**：GPU，8B-int4，`ContinuousBatchingPipeline`，cache_size=6、max_num_seqs=16、max_num_batched_tokens=32768、prefix caching=True；judge/review/review_fallback/extract/typo/function/structure 全部走本地。
- **向量**：NPU 优先（batch=1，16 窗口/s）；GPU 空闲可接；CPU 只作兜底。若 NPU+CPU 同时跑，按约 9:1 分配窗口。
- **重排**：GPU（NPU 编译失败）。
- **单篇估算**：
  - 200 次 judge：508 对实测 911.6 s → 0.557 对/s，200 对约 **359 s（6.0 min）**；把 judge 输出上限从 1024 降到 256、并利用 prefix caching 后可压到约 3–4 min。
  - 加 12 extract + 12 typo + 31 function（55 次）：按同样批处理吞吐约 99 s；LLM 合计约 7.6 min（1024 上限）。
  - 端到端实测（T4）：中文 533.2 s（8.9 min）、英文 736.0 s（12.3 min），主要耗时在文献网络请求与 support 层。
- **资源警告**：英文 T4 峰值 RSS 18.07 GB、最低可用 2.61 GB，超过 16 GB/3 GB 限制；需要把 `batch_cache_size` 降到 2–4，或限制 support 层并发。

## 9. 本地 judge 准确率（T3）

| 组 | injected | true_issue | false_alarm | failed | 证据降级 | 墙钟 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 云端 flash 基线 | 37 / 41 | 39 / 52 | 233 / 415 | 0 | — | — |
| 8B GPU 批处理 | 27 / 41 | 24 / 52 | 127 / 415 | 8 | 120 | 911.6 s |
| 4B GPU | — | — | — | 508 | — | 加载失败 |
| 8B-cw NPU（256 上限） | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 |

- 8B 与云端逐条一致 311/500（62.2%）；本地更保守，false_alarm 少但召回也低。
- 120 条 evidence 无法逐字定位被降级为 undetermined，是召回损失的主要来源。

## 10. 备注

- Qwen3.5 放弃（VLM IR；LLMPipeline 不支持，VLMPipeline 关不掉 thinking）。
- 4B 加载失败（Reshape 动态边界，OpenVINO 2026.4.1）。
- NPU 的 extract/向量不要与大模型共存：会互相拖慢约 3 倍。
- NPU judge 用 256 token 上限后约 8.8 s/对，200 对约 29 min，不适合实时判断。
- 详细命令与偏差记录见 `LOG.md`，任务进度见 `PROGRESS.md`，晨报见 `MORNING_REPORT.md`。
