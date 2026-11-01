# Intel 本地 AI 挑战：移植方案

决赛规则要求在组委会提供的 Intel 电脑上，本地实际运行至少一项与核心场景相关的 AI 能力，并说明本地与云端的处理边界。只在那台电脑上调用云端或播放录屏，不算完成。这一项计入完成度和技术实现两个维度。

## 1. 现状

| 部分 | Windows 上能否直接运行 | 说明 |
| --- | --- | --- |
| Python 后端依赖 | 能 | `pyproject.toml` 里全是纯 Python 或有 Windows wheel 的包（lxml、rapidfuzz、pypdf 等） |
| 文件读写编码 | 能 | 所有 `open` / `read_text` 都显式写了 `encoding`，不会被 GBK 默认编码坑 |
| 路径 | 能 | LaTeX 相对路径统一 `as_posix()` |
| 本地模型 | 不能 | `llm/local.py` 只支持 mlx-lm，仅限 Apple 芯片 |
| LaTeX 插图转换 | 部分 | `parse/assets.py` 调 `qlmanage` / `sips`，Windows 上没有，会静默跳过，插图不显示，体检不受影响 |
| Electron 主进程 | 小改 | Python 路径、`hiddenInset`、`vibrancy`、`open-file` 都是 mac 写法 |
| 界面 | 小改 | 根节点透明依赖 vibrancy；左上角给红绿灯留了位置；快捷键提示写的是 ⌘ |
| 打包 | 重写 | `bundle-python.sh` 和 `electron-builder --mac` 只针对 mac |

现在本地模型只接了一个任务：`router.py` 让 `extract`（论断抽取、`parse/bibguess.py` 的著录猜测）优先走本地，失败就回落云端。向量检索 `llm/embed.py` 和重排 `llm/rerank.py` 走的都是云端接口。

结论：后端几乎不用改，工作量集中在两处：本地推理引擎换成 OpenVINO，以及 Electron 壳适配 Windows。

## 2. 本地跑什么

### 推荐：证据检索和论断抽取放到本地，支持度复核留在云端

| 能力 | 模型 | 设备 | 替换的位置 |
| --- | --- | --- | --- |
| 被引原文向量检索 | Qwen3-Embedding-0.6B（OpenVINO 官方 int8 IR） | NPU，不行就用 GPU | `llm/embed.py` 新增本地后端 |
| 论断抽取 | Qwen3-1.7B 或 Qwen3-4B（OpenVINO int4） | NPU / GPU | `llm/local.py` 新增 OpenVINO 引擎 |
| 候选片段重排（可选） | Qwen3-Reranker-0.6B | GPU / CPU | `llm/rerank.py` 新增本地后端 |

选这几项的理由：

1. **紧扣核心场景。** "被引文献是否支持这句话"是 Clover 的卖点，证据检索是它的第一步。本地检索决定了复核时能拿到哪段原文，评委不会觉得是为了凑挑战硬塞的功能。
2. **把隐私说法升级。** 现在开启向量检索时，被引 PDF 的正文要切片上传。改成本地后，稿件和被引全文都不出本机，云端只看到需要复核的论断和几段证据。这句话可以直接写进路演。
3. **现场好验证。** 断网后检索和抽取照常运行；任务管理器里能看到 NPU 占用；界面上每条证据标出"本机检索"。
4. **风险低。** 0.6B 向量模型很小，OpenVINO 有官方转换好的 IR；论断抽取已经有路由和回落云端的逻辑，只换引擎。

支持度判断、期刊评审仍走云端 Qwen。这是正常的端云分工，规则也允许，只要讲清楚边界。

### 为什么不用 8–9B 模型

- 没有找到开源的 Qwen3.8-9B。Qwen3.8 目前开源的是 Max 和 27B，9B 档是 Qwen3.5-9B（2026 年 3 月）。
- Qwen3.5-9B 用了 Gated DeltaNet 混合结构。OpenVINO 官方没有给出它在 NPU 上的运行路径；唯一跑通的是社区项目，手工改写计算图，用的还是 nightly 版本，48 小时内不可依赖。
- Qwen3-8B 是传统 Transformer，OpenVINO 2025.3 起官方支持 NPU，有官方 int4 IR（`OpenVINO/Qwen3-8B-int4-cw-ov`）。社区实测 NPU 解码约 10 token/s，同机 Lunar Lake 核显约 20–25 token/s；NPU 管线默认最长输入 1024 token；16GB 内存的机器上 7B 以上模型配长输入可能不够用。
- Clover 的论断抽取要逐句调用，一篇综述可能有一两百句。按 8B 在 NPU 上每句约 10 秒算，要半小时以上。4B 在 Lunar Lake NPU 上实测解码约 24 token/s、读入约 650 token/s，1.7B 更快。
- NPU 最擅长的是只读入、不生成的计算，正好对应向量检索。所以 NPU 跑向量模型，论断抽取用 1.7B 或 4B。8B 只适合作为"能跑"的演示，不进主流程。

### 端云边界（路演用）

- **本机**：docx / LaTeX / PDF 解析，BM25，向量检索，论断抽取，错别字初筛，导出 Word 批注与修订
- **云端 Qwen**：支持度复核、期刊评审
- **联网检索（不是 AI）**：Crossref、OpenAlex、Semantic Scholar、arXiv 核验文献真实性

## 3. 技术要点

### 3.1 OpenVINO 引擎

`llm/local.py` 已经把引擎包在一个单线程执行器里，对外只暴露 `generate_json`。新增一个 `OpenVINOEngine`，接口不变：

- `openvino_genai.LLMPipeline(model_dir, device)` 生成文本；`device` 按 `NPU → GPU → CPU` 依次尝试，加载成功的那个记进状态，设置页显示出来。
- 能用 `StructuredOutputConfig(json_schema=...)` 就约束 JSON 输出；文档示例只在 CPU 上演示过，NPU 是否支持需要实机测。不支持也没关系，现有的 `_extract_json` 加 Pydantic 校验和一次重试已经能兜住。
- NPU 只接受固定形状，首次编译慢（可能几十秒）。启动后在后台预热，并打开 OpenVINO 的模型缓存目录，第二次启动就快了。
- `config.toml` 的 `[llm.local]` 增加 `engine = "mlx" | "openvino"` 和 `device`，模型名照旧走配置，不在代码里写死（AGENTS 5.2）。

### 3.2 本地向量

`embed.py` 已有按文本缓存、失败回落 BM25 的逻辑，加一个本地分支：

- 用 `optimum.intel.OVModelForFeatureExtraction` 或 OpenVINO GenAI 的 `TextEmbeddingPipeline` 加载 `OpenVINO/Qwen3-Embedding-0.6B-int8-ov`。模型卡写的是 Optimum Intel 的加载方式，GenAI 管线在 NPU 上能不能跑需要实测。
- Qwen3-Embedding 只在查询端加指令，用最后一个 token 池化，L2 归一化。要和现有 `_INSTRUCT` 保持一致，并抽几条和云端 `text-embedding-v4` 的结果比对排序。
- 缓存键带上模型名，本地和云端的向量不会混用。

### 3.3 依赖

新增 `openvino`、`openvino-genai`、`openvino-tokenizers`，放进 `pyproject.toml` 的可选依赖组 `intel`，不进默认依赖，mac 版不受影响。若采用 Optimum Intel，还会带上 transformers 和 torch，体积很大，所以优先用 GenAI 管线。AGENTS 5.4 要求新增大型依赖时说明理由：理由是决赛挑战本身要求本地运行。

## 4. Windows 适配清单

**主进程 `app/src/main/index.ts`**

- `PYTHON`：win32 下是 `python/python.exe`；开发模式用 `CITECHECK_PYTHON` 环境变量指过去。
- 窗口：win32 下用 `titleBarStyle: 'hidden'` 加 `titleBarOverlay`（颜色取当前主题），`vibrancy` 换成 `backgroundMaterial: 'mica'`，`backgroundColor` 给实色。
- 菜单：Windows 上隐藏应用菜单或设 `autoHideMenuBar`。
- 打开文件：`open-file` 只在 mac 上触发；Windows 从 `process.argv` 和 `second-instance` 事件取路径。拖入不受影响。
- spawn 环境变量加 `PYTHONUTF8=1`，作为编码的双保险。

**界面**

- 在 `<html>` 上挂平台标记（preload 把 `process.platform` 传过来），给 Windows 一组覆盖规则：侧栏底色用 `--bg-subtle`；不再给左上角红绿灯留位置；右上角给窗口按钮留约 140px，别让检查器的按钮被盖住。
- 快捷键提示 ⌘ 换成 Ctrl，按键处理已经同时认 `metaKey` 和 `ctrlKey`。
- 字体栈追加 `"Segoe UI Variable", "Microsoft YaHei UI"`，仍然只用系统字体。设计 token 和行高不动，过一遍截图检查中文行高。

**打包**

- 现场可以直接用开发模式（venv 加 `npm run dev`）演示，规则只要求设备提前装好并调试完成。
- 有余力再写 `bundle-python.ps1`，用 `electron-builder --win nsis` 出安装包，方便赛后提交。

## 5. 时间安排

规则要求本地 AI 能力在 48 小时内完成，赛前已有的基础要如实说明。建议这样切分：

**赛前（10 月 31 日至 11 月 4 日）：只做平台和可行性验证**

1. Windows 适配（第 4 节），在一台 Windows 机器上把现有 Clover 跑通，云端模式完整体检一篇样例。
2. 写一个一次性的验证脚本：在 Intel 机器上加载 Qwen3-Embedding-0.6B 和 Qwen3-1.7B，分别记下 NPU、GPU、CPU 能否加载、首次编译时间、单次耗时。这个脚本不并入产品。
3. 提前下载好模型 IR，放进 U 盘。现场网络不可靠，hf-mirror 也可能慢。
4. 问清组委会电脑型号（是否酷睿 Ultra、是否带 NPU、Windows 版本、能否装 Python 和驱动）。

**48 小时内：本地 AI 能力本身**

| 时段 | 内容 |
| --- | --- |
| 0–12h | `OpenVINOEngine` 和本地向量接入，跑通测试 |
| 12–24h | 设置页显示本地设备和端云边界；证据卡标"本机检索"；断网也能跑完的流程 |
| 24–36h | 评测：本地和云端在 `demo/testset` 上的检索命中率、抽取一致率、耗时、单篇成本 |
| 36–44h | 稳定性；把演示样例在那台机器上反复跑通；录备用视频 |
| 44–48h | 赛期成果说明、路演页 |

第 24–36h 的评测数字是"48 小时迭代带来的实际价值"最好的证据，例如"本地检索与云端前 5 条重合率 X%，单篇成本从 0.19 元降到 Y 元，被引全文零上传"。

## 6. 风险与回退

| 风险 | 回退 |
| --- | --- |
| NPU 编译失败或不支持某个算子 | 切到 Intel 核显（GPU）；仍是本地推理，挑战照样成立 |
| NPU 上结构化输出不可用 | 不约束输出，靠 `_extract_json` 加校验重试 |
| 1.7B 抽取质量不够 | 换 4B；或本地只做向量检索，抽取留在云端 |
| 组委会电脑装不了驱动或 Python | 赛前问清；带好离线安装包 |
| 首次编译太慢 | 开机预热，加模型缓存目录 |

## 7. 待确认

- 实验室那台机器的 CPU 型号，能否当赛前的 Intel 测试机（WSL 里跑不了 NPU，得在 Windows 侧装）。
- 组委会电脑的具体配置。
- 是否参加联想平板挑战。建议不参加，把时间集中在主赛。

## 参考

- [OpenVINO 发布说明](https://docs.openvino.ai/releasenotes)：2025.3 起 NPU 支持 Qwen3-1.7B / 4B / 8B
- [OpenVINO/Qwen3-Embedding-0.6B-int8-ov](https://huggingface.co/OpenVINO/Qwen3-Embedding-0.6B-int8-ov/commit/ad8959fd5a8e2d887837b89f25f48fff128368dc)：官方 int8 IR
- [OpenVINO GenAI 结构化输出](https://openvinotoolkit.github.io/openvino.genai/docs/guides/structured-output)
- [OVMS 向量服务示例](https://docs.openvino.ai/2026/model-server/ovms_demos_embeddings.html)
