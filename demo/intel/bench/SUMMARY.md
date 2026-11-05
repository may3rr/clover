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
| Qwen3-8B-int4-ov | 4.66 GB | 完成，下载前预检哈希一致 |
| Qwen3-8B-int4-cw-ov | 4.50 GB | 下载中 |
| Qwen3-4B-int4-ov | 2.16 GB | ModelScope 版本哈希不符，待从 hf-mirror 重下 |

Qwen3.5 系列未下载，仓库与大小见 `ov_models.json`。

## 2. probe.py 基线（1.7B / Embedding / Reranker）

| 任务 | 设备 | 能否加载 | 冷加载 | 缓存后加载 | 单次推理 |
| --- | --- | --- | ---: | ---: | --- |
| Embedding | CPU | ✅ | 2.94 s | 0.84 s | 24 窗口 1.24 s；3 查询 0.15 s |
| Embedding | GPU | ✅ | 8.80 s | 1.06 s | 24 窗口 0.96 s；3 查询 0.45 s |
| Embedding | NPU | ✅ | 101.02 s | 0.87 s | 24 窗口 1.58 s；3 查询 0.18 s |
| Reranker | CPU | ✅ | 3.15 s | — | 6 候选 1.62 s；24 候选 5.93 s |
| Reranker | GPU | ✅ | 9.57 s | — | 6 候选 0.22 s；24 候选 0.29 s |
| Reranker | NPU | ❌ | — | — | Reshape 动态边界不支持 |
| 1.7B 抽取 | CPU | ✅ | 3.03 s | — | 6.10 s / 3.20 s，JSON 均可解析 |
| 1.7B 抽取 | GPU | ✅ | 10.41 s | — | 3.71 s / 3.19 s，JSON 均可解析 |
| 1.7B 抽取 | NPU | ❌ | 超时 300 s | — | 编译 40+ 分钟未完成 |

- Embedding 三设备的 top-1 检索结果都与预期一致。
- Reranker NPU 报错原文：
  `Compilation failed. vclAllocatedExecutableCreate4 result: 0x78000004 ... Reshape node ... expected exactly 1 dynamic output bound dimension, got 2`
- 1.7B 是**非对称、按组量化**的 int4，NPU 编译超时；按结论不再把这类模型放到 NPU 上测，NPU 用对称逐通道的 `-cw-` 版本。

## 3. Windows 前端

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

## 4. 待完成

- GPU 8B 的批量并发测试（`batch_test.py`）。
- GPU/NPU 8B 的真实 prompt 质量测试。
- NPU 8B-cw 的编译缓存、MAX_PROMPT_LEN、组合负载测试。
- 4B / Qwen3.5-9B / Qwen3.5-4B 的 probe 与批量测试。
- 全量 sha256 复核与单篇耗时估算。

详细命令与偏差记录见 `LOG.md`。
