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

---

# ebc752c 之后：配置 C（2026-11-06 下午）

配置 C：判断、复核、论断抽取全部云端，review 也用 qwen3.8-flash；向量和重排在本机 GPU。三次运行都用全新 cache，内存红线 16 GB / 3 GB。

## 8. 三次运行的汇总

| 运行 | 墙钟 s | 支持度层 | 真实性 / 分布 / 规范 | 云端调用 | 云端花费 | 本地调用 | 向量片段 | 向量时间戳跨度 | 峰值 / 最低可用 | 注入检出 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| intel_c_zh | 535.7 | 535.5 | 44.3 / 74.8 / 60.7 | 461 | 0.4036 元 | 254（embed 165 + rerank 89） | 19,420 | 387 s | 9.75 / 10.73 GB | **14 / 17** |
| intel_c_zh_k128 | 466.6 | 466.5 | 68.6 / 72.2 / 60.2 | 458 | 0.3966 元 | 251（embed 162 + rerank 89） | 13,269 | 367 s | 12.05 / 8.49 GB | **13 / 17** |
| intel_c_en | 619.8 | 619.7 | 160.7 / 97.1 / 77.9 | 684 | 0.5310 元 | 359（embed 226 + rerank 133） | 7,713 | 475 s | 14.06 / 6.91 GB | **12 / 16** |

云端调用明细（extract / judge / review / typo / structure / function）：

| 运行 | extract | judge | review | typo | structure | function |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| intel_c_zh | 65 | 253（15 缓存） | 22 | 65 | 16 | 40 |
| intel_c_zh_k128 | 65 | 250（15 缓存） | 22 | 65 | 16 | 40 |
| intel_c_en | 96 | 351（22 缓存） | 35 | 120 | 11 | 71 |

- 三次都没有 `APITimeoutError`（B 配置的 12 条“模型输出无效”在 C 里消失），也没有本地模型加载失败。
- 配置 C 没有本地 8B，英文稿峰值 14.06 GB，**不再触发 B 配置的 18.6 GB 红线**。英文墙钟 619.8 s，比中文多 84 s，主要是真实性层 160.7 s（54 条参考文献、外部检索更重）。
- 花费结构（C 中文）：extract 0.0280、judge 0.2620、review 0.0563、typo 0.0173、structure 0.0248、function 0.0152 元。review 换成 flash 后，从 B 的 0.67 元降到 0.056 元。
- 向量：GPU 上 19,420 个片段的时间戳跨度 387 s，支持度层 535.5 s（72%）；按之前 GPU 84 片段/s 折算净算力约 231 s（43%）。同样的片段在 B 的 NPU 上要 1988 s（94%），这是配置 C 墙钟从 2116 s 降到 536 s 的主要原因。
- `prefilter_k = 128`：片段从 19,420 降到 13,269（-32%），墙钟 535.7 → 466.6 s（-69 s，-13%），花费基本不变（-0.007 元），但中文检出从 14/17 掉到 13/17，丢的是 number_rcnn。GPU 上向量本来不是瓶颈，预选的收益有限；到 NPU 上才会是数量级差别。

## 9. 三次运行的每一条漏检（对照 Mac 全云端）

Mac 全云端的逐条结果来自 `cn/master:demo/intel/bench/mac_cloud_injections.json`（`zh` 17/17、`en` 16/16）。C 的结论取自三次运行的 report JSON，原因按五类归：外部检索限流/不可用、云端超时、论断未抽出、片段里没有证据、判断给了支持或部分支持。

| 运行 | 注入 | 层 | C 的实际结论 / 状态 | C 的原因 | Mac 全云端怎么报的 |
| --- | --- | --- | --- | --- | --- |
| intel_c_zh | fake_en | 真实性 | `ref_check=unverifiable`，issues「检索服务暂不可用，未能完成核验」；finding「暂时无法核验这篇文献」 | **外部检索限流/不可用**：OpenAlex 免费日额度耗尽、Crossref/arXiv 限流 | `status=not_found`「Crossref、OpenAlex、arXiv 均未检索到相符文献」→ 检出 |
| intel_c_zh | chimera | 真实性 | 同上，`unverifiable` +「暂时无法核验」 | **外部检索限流/不可用** | `status=not_found`，同上 → 检出 |
| intel_c_zh | misattr_topic | 支持度 | 论断抽出（c59「借鉴了文献对关键点检测的思想」）；support `undetermined`「未能获取被引文献原文」；r40 同时 `unverifiable` | **外部检索限流/不可用**：r40（Attention Is All You Need）不在 52 个本地 PDF 里，网页抓取也失败 | r40 `verified`（OpenAlex）；两条 support 都是 `unsupported`（abstract），理由「Attention 是序列转换，与 CornerNet 的关键点检测不符」→ 检出 |
| intel_c_zh_k128 | fake_en | 真实性 | 同 C 中文 | **外部检索限流/不可用** | `not_found` → 检出 |
| intel_c_zh_k128 | chimera | 真实性 | 同 C 中文 | **外部检索限流/不可用** | `not_found` → 检出 |
| intel_c_zh_k128 | misattr_topic | 支持度 | 同 C 中文 | **外部检索限流/不可用** | `verified` + `unsupported` → 检出 |
| intel_c_zh_k128 | number_rcnn | 支持度 | 论断抽出但被小数点截断（「…达到了78.」）；r15 `verified`、有全文；support `undetermined`，理由是片段只提到 VOC2012 53.3% / VOC2007 约 16%，没有 78 和 58.5% | **片段里没有证据（本地向量预选）**：k=128 只嵌入 BM25 前 128 个窗口，58.5% 那一行被排除；不加预选的 C 中文能检出（`unsupported`） | r15 `verified`（Crossref）；support 有一条 `unsupported`「原文 VOC 数据与 78 严重不符」→ 检出 |
| intel_c_en | fake_en | 真实性 | `unverifiable` +「检索服务暂不可用」 | **外部检索限流/不可用** | `not_found` → 检出 |
| intel_c_en | chimera | 真实性 | 同上 | **外部检索限流/不可用** | `not_found` → 检出 |
| intel_c_en | wrong_year | 真实性 | `unverifiable` +「检索服务暂不可用」 | **外部检索限流/不可用**：Hochreiter1997 的数据库记录没取到 | `status=mismatch`「年份不一致：文中写 1993，数据库记录为 1997」（OpenAlex）→ 检出 |
| intel_c_en | misattr_topic | 支持度 | 论断抽出（c35「σ denotes ReLU」）；support `undetermined`「未能获取被引文献原文」 | **外部检索限流/不可用**：r18（Product Quantization）原文没取到 | r18 `verified`（Crossref）；一条 `undetermined` + 一条 `unsupported`「乘积量化与 ReLU 完全无关」→ 检出 |

归类统计（按 11 条运行×注入计）：

- **外部检索限流/不可用：10 条**。全部是真实性状态 `unverifiable`，或支持度因「未能获取被引文献原文」而 `undetermined`。
- **片段里没有证据（本地向量预选）：1 条**，即 k128 的 number_rcnn。去掉预选的 C 中文检出，Mac 也检出，说明是预选丢了证据窗口，不是 judge 能力问题。
- **云端超时：0 条**。C 的三次运行 `APITimeoutError` 都是 0；B 配置的 number_rcnn / number_spp 是 12 条「模型输出无效」造成的，属于另一个问题。
- **论断没抽出来：0 条**。所有漏检的支持度注入都抽出了论断；number_rcnn 只是被小数点截断（「78.」），但仍然抽出来了。
- **判断给了支持或部分支持：0 条**。C 的漏检里没有一条是 judge 明确判了 supported/partial 而没报。

结论：**配置 C 的漏检基本全是会场网络/检索限流造成的**（10/11）；只有 k128 的 number_rcnn 是本地向量预选造成的，去掉预选就不丢。Mac 全云端能 17/17、16/16，靠的是当时三个检索源可用；C 在同一台机器上把向量放本地并没有引入新的漏检（C 中文 14/17 的三条与 Mac 的差异全部在真实性/检索服务）。

> 说明：B 配置的 3 条（misattr_topic、number_rcnn、number_spp）另见上面的 B 章节：misattr_topic 是 r40 无原文；number_rcnn/number_spp 是 12 条云端 judge 超时（report 记「模型输出无效」），其中 number_rcnn 的论断还被小数点截断。C 没有超时，这两条都检出了。

## 10. 隐私模式 `intel_privacy_zh`

配置：在 C 的基础上 `[privacy] enabled = true`；本地 8B 负责 `typo / function / structure / extract / profile`；判断和复核仍走云端 qwen3.8-flash；重排 GPU。

### 10.1 内存：三次尝试

| 尝试 | 本地 8B | 向量 | 结果 |
| --- | --- | --- | --- |
| 1 | 批处理，cache 2.0 | GPU | 295 s 时峰值 **17.04 GB**，超过 16 GB 红线，终止 |
| 2 | 关批处理，cache 2.0（字段保留） | GPU | 827 s 时峰值 **18.25 GB**、可用 2.99 GB，终止 |
| 3 | 批处理，cache 2.0 | **NPU** | 完成：2254.7 s，峰值 **14.64 GB**，最低可用 6.88 GB |

- 本地 8B + GPU 向量 + GPU 重排三者常驻，16 GB 装不下；把向量换到 NPU 后，内存与 B 配置的 14.26 GB 接近。
- 这是本轮唯一一处偏离配置 C 的地方：配置 C 的三次运行按任务单用 GPU 向量，隐私模式为过内存红线改用 NPU。其余（判断/复核云端、review flash、并发 4、本地任务列表）不变。

### 10.2 耗时、花费与本地/云端调用

| 指标 | 值 |
| --- | ---: |
| 墙钟 | 2254.7 s（37.6 min） |
| 支持度层 / 分布 / 规范 / 真实性 | 2246.4 / 254.8 / 214.0 / 72.4 s |
| 云端花费 | **0.265 元**（judge 0.2205 + review 0.0446） |
| 云端调用 | judge 240（10 缓存）、review 18 |
| 本地调用 | extract 65、typo 65、function 40、structure 17、embed 163、rerank 87；失败 0 |
| 向量片段 | 19,065 |
| 向量时间戳跨度 | 1932 s（15:14:41–15:46:48），支持度层 2246 s（86%） |
| 峰值 / 最低可用 | 14.64 / 6.88 GB |
| 注入检出 | 12 / 17 |

- 隐私模式下 `extract / typo / function / structure` 全部走本地 8B，云端不再收到任何稿件正文；云端只剩 judge 和 review。
- 22.5 分钟的墙钟主要花在 NPU 向量（1932 s）和本地 8B 的逐条/批处理生成上；比 C 的 536 s 慢 4 倍，但云端花费从 0.40 元降到 0.265 元。
- 12 条云端 `APITimeoutError`（约 12 次 judge）仍然存在，导致 number_rcnn / number_spp 又变成「模型输出无效」；三条真实性/张冠李戴漏检与 C 一样是外部检索限流。

### 10.3 发送清单（`meta.send`）

`demo/intel/bench/e2e/privacy_send.json`：

| 项 | 值 |
| --- | ---: |
| privacy | true |
| 稿件正文字符 | 11,700 |
| 云端请求 | 248（10 条缓存命中） |
| 本地请求 | 437 |
| 发送总字符 | 701,845 |
| 其中用户内容 | 505,415 |
| **稿件正文发送字符** | **5,910** |
| skipped | 无（本地模型可用） |

按类目：

| 类目 | 去重条数 | 字符 | 说明 |
| --- | ---: | ---: | --- |
| claim（论断） | 54 | 5,910 | 带引用的论断句，隐私模式允许发送 |
| excerpt（被引片段） | 98 | 279,249 | 被引文献的窗口，判断需要 |
| reference（参考文献） | 55 | 10,788 | 条目和标题 |
| manuscript（稿件正文） | **0** | **0** | 题目、摘要、章节标题、图表题注、错别字上下文全部没发 |
| exemplar / other | 0 | 0 | |

- 隐私模式按设计生效：`manuscript_sent_chars = 5,910`，正好等于 claim 类的 5,910，**没有任何 manuscript 类内容**。本地 8B 处理的五个任务没有把稿件正文送到云端。
- 248 次云端请求里，judge/review 的 prompt 里带的是 claim + excerpt + reference；向量和重排都是本地，不出现在发送清单里。
- `skipped` 为空，因为本地 8B 可用；如果本机没有模型，typo/function/structure/extract/profile 会整项跳过，而不是回落云端。


