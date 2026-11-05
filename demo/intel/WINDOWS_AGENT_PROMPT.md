# 任务：在这台 Intel 笔记本上准备 Clover 的本地模型环境，并测出本地 Qwen 模型的能力边界

> 这份文件是给 Intel Windows 决赛机上的 agent 的任务说明。
> 第一轮只做第 1 到第 3 步（环境、下载、跑通现有脚本），做完把结果推回 GitCode，等待下一步指示。第 4 步在收到明确指示后再做。

## 背景

Clover 是一个论文引用体检工具，后端是 Python 3.11 加 FastAPI。仓库是 https://gitcode.com/may3rr/clover.git，这台电脑只能访问 GitCode。

决赛要求在 Intel 电脑上本地运行 AI 能力。我们想知道这台机器（Core Ultra 5 338H，Arc B370 核显，NPU，32GB 内存）能把多少模型调用从云端挪到本地。

克隆仓库后，先通读这几份文件：

- `AGENTS.md`，尤其是 5.5 节"两台电脑的同步"
- `demo/intel/README.md`
- `design/Intel本地化移植方案.md`
- `backend/citecheck/llm/ov.py`
- `backend/citecheck/llm/local.py`

## 规则

- 不要修改 `backend/citecheck/` 下的产品代码。新写的脚本和结果一律放在 `demo/intel/bench/`。
- Git 按 `AGENTS.md` 5.5 节执行：
  - 只在 `intel` 分支上提交；
  - 完成一步就执行 `git push cn intel`；
  - 不要推 `master`，不要 `--force`。
- 失败要如实记录，把报错原文写进结果，不要跳过，也不要只报成功的那部分。
- 网络走国内镜像：HuggingFace 用 `https://hf-mirror.com`，PyPI 用阿里云或清华源。
- 每一步命令都记进 `demo/intel/bench/LOG.md`，方便复现。
- 模型放在仓库外的 `C:\clover-models`，不要提交模型文件。大于 10MB 的文件都不要提交。

## 第 1 步：环境与代码

1. 安装 uv：`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`。失败就用 `winget install astral-sh.uv`。
2. 安装 Git：`winget install --id Git.Git -e`。装完后重开终端。然后执行：
   - `git config --global core.autocrlf false`
   - `git config --global user.name` 和 `git config --global user.email`，名字和邮箱向用户要
3. 设置环境变量（用户级，写进系统，不只是当前会话）：
   - `UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/`
   - `HF_ENDPOINT=https://hf-mirror.com`
   - 如果 uv 下载 Python 很慢，再加 `UV_PYTHON_INSTALL_MIRROR=https://registry.npmmirror.com/-/binary/python-build-standalone/`
4. 获取代码：
   ```powershell
   git clone https://gitcode.com/may3rr/clover.git C:\clover
   cd C:\clover
   git remote rename origin cn
   git checkout -b intel cn/master
   ```
   远端改名为 `cn`，是为了和 `AGENTS.md` 里的命令对上。第一次 `git push` 时会要求登录 GitCode，用账号加访问令牌，向用户要。
5. 安装后端依赖：
   ```powershell
   cd C:\clover\backend
   uv venv --python 3.11
   uv pip install -e ".[dev,intel]" psutil huggingface_hub
   ```
6. 跑一遍测试：`.venv\Scripts\python -m pytest -q`，记下通过和失败的数量。需要网络或 API Key 的用例失败可以接受，记下来就行。
7. 确认设备：`.venv\Scripts\python -c "import openvino as ov; print(ov.Core().available_devices)"`，应能看到 CPU、GPU、NPU。看不到 NPU 或 GPU 的话，记下驱动版本，然后继续往下做。
8. 测试前把电源模式切到最佳性能，插上电源，关掉不用的程序。记下空闲时的可用内存。

## 第 2 步：下载模型到 C:\clover-models

先用 `https://hf-mirror.com/api/models?author=OpenVINO&search=Qwen3` 列出 OpenVINO 官方组织下所有 Qwen 模型，存进 `demo/intel/bench/ov_models.json`。然后用 `hf download <repo> --local-dir C:\clover-models\<目录名>` 下载以下模型（如果没有 `hf` 命令，就用 `huggingface-cli download`）：

| 目录名 | 仓库 | 用途 |
| --- | --- | --- |
| Qwen3-Embedding-0.6B-int8-ov | OpenVINO/Qwen3-Embedding-0.6B-int8-ov | 向量检索 |
| Qwen3-Reranker-0.6B-int8-ov | OpenVINO/Qwen3-Reranker-0.6B-int8-ov | 重排 |
| Qwen3-1.7B-int4-ov | OpenVINO/Qwen3-1.7B-int4-ov | 小模型基线 |
| Qwen3-4B-int4-ov | OpenVINO/Qwen3-4B-int4-ov | 候选 |
| Qwen3-8B-int4-ov | OpenVINO/Qwen3-8B-int4-ov | 候选 |
| Qwen3-8B-int4-cw-ov | OpenVINO/Qwen3-8B-int4-cw-ov | NPU 用的对称逐通道量化版 |

- 如果列表里还有 4B 的 `-cw-` 版本，或者更新的、10B 以下的 Qwen 版本（例如 Qwen3.5），也一并下载。
- 列表里没有的仓库，记一句"不存在"后跳过。不要自己转换模型，转换需要装 torch，太重。
- 记下每个模型的磁盘大小。
- 全部下载大约 15GB。可以先下前三个，跑第 3 步，同时在后台下载其余的。

## 第 3 步：跑现有的可行性脚本

```powershell
cd C:\clover\backend
.venv\Scripts\python ..\demo\intel\probe.py --models C:\clover-models --out ..\demo\intel\bench\probe.json
```

这个脚本会在 CPU、GPU、NPU 上逐个加载向量、重排和 1.7B 模型，记录：

- 能否编译；
- 冷加载和缓存后的加载耗时；
- 单次推理耗时；
- 向量结果与 CPU 的一致程度。

4B 和 8B 下载完后，用 `--llm` 再各跑一次，只测 LLM：

```powershell
.venv\Scripts\python ..\demo\intel\probe.py --models C:\clover-models --llm Qwen3-4B-int4-ov --only llm --out ..\demo\intel\bench\probe-4b.json
.venv\Scripts\python ..\demo\intel\probe.py --models C:\clover-models --llm Qwen3-8B-int4-ov --only llm --out ..\demo\intel\bench\probe-8b.json
.venv\Scripts\python ..\demo\intel\probe.py --models C:\clover-models --llm Qwen3-8B-int4-cw-ov --only llm --out ..\demo\intel\bench\probe-8b-cw.json
```

**第一轮到这里结束。** 写一份 `demo/intel/bench/SUMMARY.md`（中文），内容包括：

- 环境安装情况：哪些步骤顺利，哪些出了问题、怎么解决的；
- pytest 结果；
- OpenVINO 能看到的设备；
- 实际下载到的模型和大小；
- 一张表：模型 × 设备 → 能否加载、冷加载、缓存后加载、单次耗时，抽取任务再加上 JSON 是否可解析；
- 所有失败项和报错原文。

然后提交并推送：

```powershell
git add demo/intel/bench
git commit -m "Intel bench round 1: environment, model download, probe"
git push cn intel
```

## 第 4 步（等指示后再做）：新写 demo/intel/bench/bench_llm.py

对每个 LLM 目录和每个设备（GPU、NPU、CPU）的组合测下面这些项。加载模型复用 `citecheck.llm.ov.Generator`，先读它的构造参数；需要细粒度计时就直接用 `openvino_genai.LLMPipeline` 和 `PerfMetrics`。每完成一个组合就把结果写进 JSON，避免中途崩溃丢数据。

1. **加载。** 分别测冷编译耗时（缓存目录为空）和缓存后的加载耗时。
2. **内存。** 用后台线程每 0.2 秒采一次本进程的 RSS 和系统可用内存，记下峰值。剩余内存低于 3GB 时停止这个组合，标记为"内存不足"。
3. **上下文与速度。** 输入长度取 512、1024、2048、4096、8192 token，每档生成 128 个 token。记下首 token 延迟（TTFT）、prefill 速度（token/s）和 decode 速度（token/s）。
   - NPU 需要在编译时指定 `MAX_PROMPT_LEN`，从 1024 往上试，记下能编译通过的最大值。
   - 某一档失败，就记下错误后接着测下一档。
4. **真实任务。** 从代码里取真实的 prompt，套用对应的 Pydantic schema 校验输出：
   - judge：`support/judge.py`，输入约 1300 token，输出约 120 token
   - extract：`support/claims.py`
   - typo：`lint/typos.py` 的 `_PROMPT`
   - function：`distribution/layer.py` 的 `_FUNC_PROMPT`

   每类任务准备 6 条样例，中文和英文各一半。judge 的样例要带已知答案：
   - 2 条支持；
   - 2 条数字不符，例如论断写"每秒 50 帧"，原文写"每秒 5 帧"；
   - 2 条张冠李戴，即原文讲的是另一件事。

   原文片段可以取自 `demo/intel/probe.py` 里的 WINDOWS，也可以从 `demo/` 下的样例里找。

   记录每次调用的耗时、JSON 是否能解析、schema 是否通过、judge 的判断是否与答案一致，并保存原始输出。必须关闭 thinking：`ov.py` 里已经处理过，确认输出里没有 `<think>`。
5. **估算单篇耗时。** 一篇论文大约有 200 次 judge、12 次 extract、12 次 typo、31 次 function 调用。用实测的单次耗时折算每个模型和设备组合跑完一篇需要几分钟。
6. **组合负载。** 选出最好的 LLM 组合，让它连续跑 judge，同时在 NPU 上跑向量（24 个窗口一批，循环执行）。测两边互相拖慢了多少，并记下峰值内存。
7. **长跑稳定性。** 在最好的组合上连续跑 100 次 judge，记下 decode 速度随时间的变化，看是否因为发热降频。

把结果写进 `results.json`，并更新 `SUMMARY.md`，增加以下内容：

- 一张表：模型 × 设备 → 峰值内存、TTFT、decode 速度、最大上下文、JSON 通过率、judge 正确数、单篇估算分钟数；
- 一段结论：judge 能否在本地跑完一篇（目标是 5 分钟以内），哪个组合最好；extract、typo、function 各用哪个组合。

最后提交并推送到 `cn intel`。
