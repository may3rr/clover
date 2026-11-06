# 推荐配置端到端（Intel，2026-11-06）

配置 B：判断和复核走云端；论断抽取、向量、重排在本机。中文稿完整跑完，英文稿在 288.7 s 触发 16 GB / 3 GB 红线被终止。所有数字都是本机实测，完整报告 JSON（含被引原文片段）留在 `C:\clover-data\prof\`，未提交。

## 1. 结论

| 指标 | 中文演示稿 |
| --- | ---: |
| 墙钟 | **2116.1 s（35.3 min）** |
| 云端花费 | **0.96 元** |
| 本地调用 | 322 次（extract 65 / embed 168 / rerank 89），失败 0 |
| 云端调用 | 382 次（judge 241 / typo 65 / function 40 / review 20 / structure 16） |
| 向量片段 | **19,424** |
| 峰值 RSS | 14.26 GB |
| 最低可用内存 | 6.27 GB |
| 注入检出 | **12 / 17** |

- **向量是绝对瓶颈**：embed 调用首末时间戳跨度 1988 s，支持度层 2116 s（94%）；按上一轮 NPU 实测 16.1 片段/s 折算，净算力约 1206 s（57%），其余是等云端 judge/review 的间隙。BM25 预选（`EMBED_PREFILTER.md`）是必需的。
- **英文稿跑不了原推荐配置**：288.7 s 时峰值 18.6 GB、可用 1.89 GB，按红线终止（exit 124）。与 T4 全本地英文稿的 18.07 GB 一致。
- **免费额度 Key 需要降级使用**：qwen3.7-flash / qwen3.7-max 返回 403 `AllocationQuota.FreeTierOnly`，已改到 qwen3.8-flash；云端并发 12 → 4 后，`APITimeoutError` 从约 40 次降到约 12 次。

## 2. 配置与偏差

`C:\clover-data\e2e-rec\config.toml`：

```toml
[llm.models]
structure = "qwen3.8-flash"
function = "qwen3.8-flash"
review_fallback = "qwen3.8-max"

[llm.cloud]
max_concurrency = 4
timeout = 120
retry_seconds = 300

[llm.local]
enabled = true
engine = "openvino"
model = "C:/clover-models/Qwen3-8B-int4-ov"
device = "GPU"
batching = true
batch_cache_size = 4.0
tasks = ["extract"]

[llm.embedding]
backend = "openvino"
local_model = "C:/clover-models/Qwen3-Embedding-0.6B-int8-ov"
device = "NPU"

[llm.rerank]
backend = "openvino"
local_model = "C:/clover-models/Qwen3-Reranker-0.6B-int8-ov"
device = "GPU"
```

偏差都来自免费额度 Key，与本地配置无关：

- `structure` / `function` / `review_fallback` 从 qwen3.7 系列改成 qwen3.8；qwen3.7 在免费额度下直接 403。
- 云端并发 12 → 4，超时 60 → 120 s，重试总时长 180 → 300 s。
- 第一次跑中文时，重排与 8B 批处理同时编译，触发一次 OpenVINO 缓存读取错误：
  `local rerank unavailable (GPU: 'utf-8' codec can't decode byte 0xc1 in position 59)`，整轮降级为不重排（19,420 片段、1871 s，10/17）。第二次用 `run_profile_preload.py` 在计时前先加载 rerank（日志 `preload rerank: device=GPU`），89 次重排调用全部正常；预热约 1 s，不计入墙钟。下表用的是第二次。

## 3. 中文演示稿 `intel_rec_zh`

输入 `demo/final/演示稿/基于深度学习的目标检测研究综述.docx`，文献夹 `C:\clover-data\refs\演示稿\ref`（52 个 PDF，全部 52 条被引文献都链接成功）。全新 cache：`C:\clover-data\prof\rec_zh.sqlite`。

### 3.1 耗时

| 项 | 秒 |
| --- | ---: |
| 墙钟 / duration | 2116.1 |
| 支持度层 | 2116.0 |
| 真实性层 | 90.8 |
| 引用分布层 | 64.7 |
| 格式规范层 | 53.6 |
| 解析 | 0.0 |

四层并发，层耗时从开始计到该层结束；支持度层就是墙钟。外部检索累计：OpenAlex 96 次 55.6 s、Crossref 100 次 430.2 s、S2 71 次 86.1 s、arXiv 74 次 81.8 s（并发请求耗时之和，不是墙钟）。

### 3.2 云端调用与花费

按 `profile_cost_speed.py` 的价格口径（qwen3.8-flash 输入 0.8 / 输出 2.7，qwen3.8-max 12 / 36 元每百万 token）：

| 任务 | 模型 | 调用 | 输入 token | 输出 token | 元 |
| --- | --- | ---: | ---: | ---: | ---: |
| judge | qwen3.8-flash | 241（15 缓存） | 198,972 | 26,180 | 0.2299 |
| review | qwen3.8-max | 20 | 47,542 | 2,838 | 0.6727 |
| typo | qwen3.8-flash | 65 | 17,255 | 1,326 | 0.0174 |
| structure | qwen3.8-flash | 16 | 8,413 | 6,704 | 0.0248 |
| function | qwen3.8-flash | 40 | 9,635 | 2,733 | 0.0151 |
| **合计** | | **382** | | | **0.9598** |

- 本地向量与重排计 0 元；论断抽取改本地后，原本的 extract token 不再计费。
- **复核用 qwen3.8-max 占了 70% 的花费**（0.67 / 0.96）。若复核也用 flash，这 47,542 / 2,838 token 只要 0.0457 元，总价约 **0.33 元**。Mac 的 0.46 元估算是全 flash 口径，两者不可直接比。

### 3.3 本地调用与失败

| 任务 | 模型/设备 | 调用 | 失败 |
| --- | --- | ---: | ---: |
| extract | Qwen3-8B-int4 / GPU，批处理 | 65 | 0 |
| embed | Qwen3-Embedding-0.6B / NPU | 168 | 0 |
| rerank | Qwen3-Reranker-0.6B / GPU | 89 | 0 |

- 本地失败 0；日志里 `local embedding failed` / `local rerank unavailable` / `local batched generation failed` 都是 0。
- 云端 `APITimeoutError` 36 行（每次失败 3 行，约 12 次调用）；OpenAlex 触发免费日额度、Crossref/S2 中途限流。

### 3.4 向量

- 片段数：**19,424**（`vectors` 表，全新 cache）。
- 时间戳跨度：13:02:39–13:35:47，**1988 s**；同一窗口内还跑了云端 judge 和本地 rerank。
- 按上一轮实测 NPU 16.1 片段/s 折算，净向量算力约 **1206 s（20.1 min）**；支持度层 2116 s，向量时间戳跨度占 **94%**，净算力占 **57%**。
- 支持度层共 111 对检查；向量是这一层的关键路径。

### 3.5 内存

- 峰值 RSS **14.26 GB**（psutil 进程树，1 s 采样），最低可用 **6.27 GB**；未触发 16 GB / 3 GB 红线。
- 运行中观察：8B 批处理 + NPU embedding + GPU rerank + Electron 全部退出，仍占 14 GB。

### 3.6 注入检出

`check_final.py`：**12 / 17**。未检出 5 条：

| 注入 | 原因 |
| --- | --- |
| fake_en | 真实性 `status=unverifiable`；OpenAlex 免费额度耗尽、Crossref 限流，编造文献无法确认 |
| chimera | 同上 |
| misattr_topic | 支持度未报；云端 judge 判 supported/partial |
| number_rcnn | 数字错误未报；同一批数字类判断漏检 |
| number_spp | 同上 |

- 其余 39 条非注入报警，主要是 20 篇被引文献没有原文（21 条论断无法判断）和少量作者归属/部分支持。
- 报告规模：149 段、73 条参考文献、96 处引用标记、81 条论断、111 对检查、47 条问题、14 处修订。

## 4. 英文演示稿 `intel_rec_en`（中止）

输入 `demo/final/英文演示稿/deep_residual_learning.zip`，文献夹 `C:\clover-data\refs\英文演示稿\ref`（29 个 PDF；zip 本身只有 29 个，任务单写 31，少 2 个）。

| 项 | 值 |
| --- | ---: |
| 中止时间 | 288.7 s |
| 峰值 RSS | **18.6 GB** |
| 最低可用内存 | **1.89 GB** |
| 中止时 extract | 95 次 |
| 中止时 typo | 119 次 |
| 中止时 judge / embed / rerank | 13 / 28 / 2 |
| 中止时向量 | 1,692 |
| 报告 | 无（未写） |

- `run_profile.py` 在峰值 RSS > 16 GB 或可用 < 3 GB 时直接杀进程，exit 124；这是任务单要求的红线。
- 原因与 T4 全本地英文稿一致：8B 批处理 KV 预分配 + NPU embedding + GPU rerank + LaTeX 解析同时占内存，峰值 18.6 GB。
- 按原推荐配置（cache 4.0、batching=true）英文稿在这台机器上**不可用**。要跑英文，需要 cache 2.0 / 关闭批处理 / 换更小的抽取模型之一；本轮按红线没有再试。

## 5. 与 Mac 的对照

`FINALS_DELTA.md` 第 2 节（Mac，演示稿冷启动）：

| 指标 | Mac 现在 | Intel 推荐配置 |
| --- | ---: | ---: |
| 中文墙钟 | 352.0 s | **2116.1 s** |
| 中文云端花费 | 2.43 元（向量/重排走 API） | **0.96 元** |
| 中文云端花费，去掉向量/重排 | 0.46 元（估算） | 0.96 元（本地向量/重排，但复核用 max） |
| 英文墙钟 | 362.5 s | 中止（18.6 GB） |

- 墙钟差 6 倍：Mac 的向量/重排走硅基流动 API，Intel 的 19,424 个片段全部在 NPU 上算，约 20–33 分钟；这是本机化的代价，也是 BM25 预选要解决的问题。
- 花费口径不同：Mac 的 0.46 元是全 flash 估算；本机复核用 qwen3.8-max，单这一项 0.67 元。把复核也换成 flash，本机总价约 0.33 元，低于 Mac 的 0.46。
- 两边的模型和向量后端都不是同一套，只能看量级和瓶颈，不能当严格 A/B。

## 6. 发现与建议

1. **先做 BM25 预选**：19,424 个片段里有大量与本条论断无关的窗口。按 `EMBED_PREFILTER.md` 的 top-K + 邻居方案，片段数可降到 2%–6%，支持度层从 35 分钟回到分钟级。
2. **英文稿的内存红线**：cache 4.0 仍到 18.6 GB。演示英文稿前必须降内存（cache 2.0 / batching=false / 1.7B 抽取），否则会触发停止线。
3. **重排与 8B 的 OpenVINO 缓存竞争**：同时编译时出现过一次 `'utf-8' codec can't decode byte 0xc1`，整轮重排失效。预热 rerank 可规避；产品侧建议给 rerank 单独的缓存目录或加载锁。
4. **免费额度 Key**：qwen3.7 系列 403；12 并发超时明显。演示用付费 Key，或把云端并发压到 4。
5. **外部检索限流**：OpenAlex 免费日额度耗尽、Crossref/S2 中途限流，导致 fake_en / chimera 两条编造文献只能标 `unverifiable`，20 篇被引文献没有原文。比赛现场要提前预热或换有 Key 的检索源。
6. **PDF 数量**：`clover-demo-refs.zip` 英文目录只有 29 个 PDF，任务单写 31；中文 52 个符合。

## 7. 复现

```bat
cd C:\clover\backend
set CITECHECK_HOME=C:\clover-data\e2e-rec
set DASHSCOPE_API_KEY=<key>
.venv\Scripts\python.exe C:\clover-data\run_profile.py --out C:\clover-data\prof\rec_zh.mem.json --log C:\clover-data\prof\rec_zh.log -- ^
  .venv\Scripts\python.exe C:\clover-data\run_profile_preload.py --tag intel_rec_zh ^
  --cache C:\clover-data\prof\rec_zh.sqlite --save C:\clover-data\prof\rec_zh.report.json ^
  "..\demo\final\演示稿\基于深度学习的目标检测研究综述.docx" "C:\clover-data\refs\演示稿\ref"

C:\clover\backend\.venv\Scripts\python.exe demo\final\check_final.py C:\clover-data\prof\rec_zh.report.json
```

- 每次用全新 `--cache` 文件；`CITECHECK_HOME` 指向 B 配置目录。
- `run_profile_preload.py` 只多做一件事：计时前 `rerank.local_reranker()`，其余调用仓库里的 `profile_cost_speed.cmd_run`，输出格式不变。
- 提交物：`demo/testset/profile_runs/intel_rec_zh_cold.json`、`intel_rec_zh_score.txt`、本文件。
- 不提交：`rec_zh.report.json`（含被引原文片段）、`rec_zh.sqlite`。
