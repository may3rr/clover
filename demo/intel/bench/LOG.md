# Intel Windows 机器：环境、模型与前端验证记录

- 日期：2026-11-05
- 机器：HP OmniBook 7 Laptop 16-bh0xxx，Core Ultra 5 338H，Arc B370，Intel NPU，32 GB LPDDR5X
- 系统：Windows 11 家庭中文版 26200，屏幕 2560×1600 @150%，电源已接通
- 仓库：`C:\clover`，分支 `intel`（基于 `cn/master` 5ea236f）

## 0. 摘要

- Git 克隆正常，GitCode SSH 直连（22 端口）可用。
- Python 3.11.18 + OpenVINO 2026.4.1 + openvino-genai 2026.4.1.0 安装成功。
- `pytest`：500 通过，2 失败，8 跳过（详见第 3 节）。
- OpenVINO 可见设备：`CPU`、`GPU`、`NPU`。
- 模型：前三个（Embedding / Reranker / 1.7B）已下载并通过 sha256 与 HF LFS 逐一比对；4B、8B、8B-cw 在本文件提交时仍在下载。
- 前端：`npm ci` + `npm run dev` 可启动；完成引导后可拖入 docx，示例稿件跑完并给出报告；无 API Key 时云端判断层失败，符合预期。

## 1. 环境安装

```powershell
# uv（便携版，经 npmmirror 镜像）
# uv 0.13.7
uv python install 3.11          # cpython-3.11.18，经 UV_PYTHON_INSTALL_MIRROR
uv venv --python 3.11           # 在 C:\clover\backend
uv pip install -e ".[dev,intel]" psutil huggingface_hub
```

- Node：`v26.13.0`（npmmirror 便携版），npm `11.20.0`。
  - 未用 `winget install OpenJS.NodeJS.LTS`：当前会话非管理员，MSI 安装需要提权；已有 Node 26 LTS 可用。
- 镜像（用户级环境变量）：
  - `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`
  - `UV_PYTHON_INSTALL_MIRROR=https://registry.npmmirror.com/-/binary/python-build-standalone`
  - `HF_ENDPOINT=https://hf-mirror.com`
  - `HF_HUB_DISABLE_XET=1`
  - `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`
- Git：MinGit 2.56.0.4；`core.autocrlf=false`；`core.sshCommand=C:/Windows/System32/OpenSSH/ssh.exe`
  - 未用 `winget install Git.Git`：从 GitHub 下载约 60 KB/s，winget 卡住；改用 npmmirror 上的 MinGit。
- GitCode：`git@gitcode.com:may3rr/clover.git`，SSH 22 端口直连可用。
  - `git remote rename origin cn`
  - `git checkout -b intel cn/master`

## 2. 依赖与测试

```powershell
cd C:\clover\backend
uv pip install -e ".[dev,intel]" psutil huggingface_hub
.venv\Scripts\python -m pytest -q
```

结果：**500 passed, 2 failed, 8 skipped in 300.76s**。

失败 1：`tests/test_pipeline.py::test_library_scan_reports_stages`
- `FileNotFoundError: ..\demo\testset\zh_pdfs\aas_yinhongpeng_2016.pdf`
- 仓库未包含该测试 PDF，属于缺资产，不是代码问题。

失败 2：`tests/test_parse_latex.py::test_tables_become_cell_paragraphs`
- `AssertionError: assert (True and '\\midr' == 'EN-FR'`
- `LaTeX.locate()` 返回的偏移落在 `\midrule` 上，而不是单元格文本 `EN-FR`；与 Windows 无关，属于仓库现有缺陷。

依赖版本偏差：
- `pyproject.toml` 未给 FastAPI 上界，uv 解析到 FastAPI 0.162 + Starlette 1.10，`app.add_event_handler` 已被移除，测试收集阶段直接报错。
- 处理：仅在 venv 中固定 `fastapi<0.116`（实际 0.115.14 + starlette 0.46.2），未修改 `backend/citecheck/` 产品代码。

## 3. 设备

```powershell
.venv\Scripts\python -c "import openvino as ov; print(ov.Core().available_devices)"
# ['CPU', 'GPU', 'NPU']
```

- OpenVINO: `2026.4.1-22982-e213a147257-releases/2026/4`
- openvino-genai: `2026.4.1.0`
- NPU 驱动：`32.0.100.4512`（2025-12-09），设备 `PCI\VEN_8086&DEV_B03E`

## 4. 模型下载

### 4.1 通道选择

- 提示词指定 hf-mirror；实测 `hf download` 在小文件阶段结束后卡在大文件上（30 秒零增长）。
- 改为 ModelScope 直链（`https://www.modelscope.cn/models/OpenVINO/<repo>/resolve/master/<file>`），实测约 3.5–3.7 MB/s。
- 一致性：下载前列出 HF 与 ModelScope 的文件清单，逐项大小一致；下载后又用 sha256 与 HF LFS oid 核对（见 4.3）。

### 4.2 下载顺序与结果

按要求顺序：Embedding → Reranker → 1.7B → 4B → 8B → 8B-cw。

| 目录 | 大小 | 状态 |
| --- | ---: | --- |
| Qwen3-Embedding-0.6B-int8-ov | 613 MB | 完成，sha256 通过 |
| Qwen3-Reranker-0.6B-int8-ov | 595 MB | 完成，sha256 通过 |
| Qwen3-1.7B-int4-ov | 1152 MB | 完成，sha256 通过 |
| Qwen3-4B-int4-ov | 2184 MB | 完成；ModelScope 版本哈希不符，已从 hf-mirror 重下并复核 |
| Qwen3-8B-int4-ov | 下载中 | 预检 ModelScope 与 HF 哈希一致 |
| Qwen3-8B-int4-cw-ov | 排队 | 提交时未开始 |

Qwen3.5 系列按要求**未下载**，仓库清单与大小已写入 `demo/intel/bench/ov_models.json`（`qwen35_not_downloaded`），共 14 个仓库，例如：

- `Qwen3.5-0.8B-int4-ov` 0.86 GB、`-int8-ov` 1.09 GB、`-fp16-ov` 2.14 GB
- `Qwen3.5-2B-int4-ov` 1.99 GB、`-int8-ov` 2.63 GB、`-fp16-ov` 5.22 GB
- `Qwen3.5-4B-int4-ov` 3.33 GB、`-int8-ov` 4.98 GB、`-fp16-ov` 9.90 GB
- `Qwen3.5-9B-int4-ov` 5.85 GB、`-nf4-ov` 5.72 GB、`-int8-ov` 9.03 GB、`-fp16-ov` 18.02 GB
- `Qwen3.5-27B-int4-ov` 14.87 GB

### 4.3 sha256 校验

校验方式：`https://hf-mirror.com/api/models/OpenVINO/<repo>/tree/main?recursive=true` 的 `lfs.oid` 与本地 `Get-FileHash -Algorithm SHA256` 对比。

```text
## Qwen3-Embedding-0.6B-int8-ov
OK  openvino_model.bin        587.8 MB
OK  openvino_detokenizer.bin    2.1 MB
OK  tokenizer.json             10.9 MB
OK  openvino_tokenizer.bin      5.3 MB

## Qwen3-Reranker-0.6B-int8-ov
OK  openvino_model.bin        569.8 MB
OK  openvino_detokenizer.bin    2.1 MB
OK  tokenizer.json             10.9 MB
OK  openvino_tokenizer.bin      5.3 MB

## Qwen3-1.7B-int4-ov
OK  openvino_model.bin       1127.0 MB
OK  openvino_detokenizer.bin    2.1 MB
OK  tokenizer.json             10.9 MB
OK  openvino_tokenizer.bin      5.3 MB
```

完整输出见 `demo/intel/bench/sha256.log`。

**4B 的哈希不一致**：ModelScope 上 `Qwen3-4B-int4-ov` 的 `openvino_model.bin` 与 `openvino_tokenizer.bin` 和 HF LFS oid 不同（大小相同、内容不同）。已删除这两个文件并从 `https://hf-mirror.com/OpenVINO/Qwen3-4B-int4-ov/resolve/main/...` 重新下载，复核通过后计入完成。8B 在下载前用 ModelScope API 返回的 `Sha256` 与 HF `lfs.oid` 预检，全部一致，不需要换源。

4B / 8B / 8B-cw 下载完成后按同一脚本补验。

### 4.4 下载日志

逐文件日志：`demo/intel/bench/download.log`。

## 5. probe.py

```powershell
cd C:\clover\backend
.venv\Scripts\python ..\demo\intel\probe.py --models C:\clover-models --out ..\demo\intel\bench\probe.json
```

脚本按 CPU → GPU → NPU 顺序加载三个模型，记录冷/热加载、24 窗口向量、3 查询向量、6/24 候选重排、1.7B 抽取与 CPU 一致性。结果见 `demo/intel/bench/probe.json` 与 `SUMMARY.md`。

## 6. Windows 前端

### 6.1 安装

```powershell
cd C:\clover\app
npm ci          # 80 s，node_modules 210 MB
node node_modules\electron\install.js   # npm ci 未执行 electron 的 postinstall，手动补装，241 s
npm run dev
```

- Electron 44.4.5，窗口标题 `Clover`。
- 后端由主进程自动拉起 `backend\.venv\Scripts\python.exe`，`/health`、`/prefs`、`/reports`、`/venues`、`/benchmarks` 均返回 200。

### 6.2 引导流程

首次启动是引导页（标题 “the last mile of the paper”），点「开始设置」进入：

1. 连接模型服务（阿里云百炼 API Key）→ 选「稍后配置」
2. 怎么称呼你 → 「继续」
3. 隐私说明 → 勾选同意 → 「开始使用」

无 API Key 可以完成引导并进入主界面。

### 6.3 拖拽测试

- 从资源管理器把 `clover-sample.docx`（60 KB）拖入主界面。
- 应用成功解析：**55 条参考文献，125 处引用**。
- 检查完成：15 个问题（文献真实性 5、论断支持度 2、引用分布 8、格式规范 0），用时 1 分 48 秒。
- 无 API Key 时后端反复输出 `llm cloud route failed for task judge: OpenAIError`；「原文比对」显示 0 组找到证据，符合降级预期。
- 截图：`screenshots/05-after-drop.png`（首次拖拽时还在引导页）、`screenshots/14-main-screen.png`（主界面）、`screenshots/16-final-before-stop.png`（报告页）。

### 6.4 观察到的 Windows 表现（未改 app/ 代码）

1. 首次启动时窗口 1294×829，首页大标题 “the last mile of the paper” 右侧被截断（`screenshots/01-home.png`）；窗口加高/加宽后完整显示。
2. 设置页与报告页在 1300 宽窗口下右侧内容被截断，报告页的「导出」按钮只露出一部分（`screenshots/16-final-before-stop.png`）。
3. 隐私页文案写的是「一切留在**这台 Mac** 上」，Windows 上未替换（`screenshots/12-consent-checked.png`）。
4. `npm ci` 不会自动下载 Electron 二进制，需要手动执行 `node node_modules/electron/install.js`。
5. 没有 API Key 时引导可跳过，但检查结果中支持度层几乎全部降级。

## 7. 偏差与未完成项

- 模型下载源从 hf-mirror 改为 ModelScope（原因与校验见 4.1）。
- Node 使用已有的 26.13.0，未重复安装 winget 的 LTS。
- Git 使用 MinGit，未用 winget。
- Qwen3.5 未下载，仅记录清单与大小。
- 第 4 步（`bench_llm.py`）按要求等待指示后再做。

## 8. GPU 8B 测试（第 2 步）

### 8.1 probe（CPU / GPU）

```powershell
cd C:\clover\backend
.venv\Scripts\python ..\demo\intel\bench\probe_timeout.py --models C:\clover-models \
  --llm Qwen3-8B-int4-ov --only llm --devices CPU,GPU --out ..\demo\intel\bench\probe-8b.json
```

| 设备 | 冷加载 | 抽取 1 | 抽取 2 | JSON |
| --- | ---: | ---: | ---: | --- |
| GPU | 18.7 s | 2.31 s / 44 tok | 2.58 s / 56 tok | 均可解析 |
| CPU | 8.9 s | 13.67 s / 44 tok | 6.16 s / 56 tok | 均可解析 |

### 8.2 连续批处理（`batch_test.py`）

- `ContinuousBatchingPipeline`，GPU，8B-int4，prompt 1315 token，`max_new_tokens=128`，`ignore_eos=True`，贪心。
- `SchedulerConfig.max_num_seqs=16`、`max_num_batched_tokens=32768`、`cache_size=8`、关闭 prefix caching。
- 注意：批处理下每个结果的 `perf_metrics.get_num_generated_tokens()` 返回的是**整批** token 数；因此按 `并发数 × 128` 计总 token。
- 峰值内存用 0.2 s 采样的进程 RSS 与系统可用内存。

| 并发 | 总耗时 | 平均每请求 | 总吞吐 | 峰值 RSS | 最低可用内存 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 8.53 s | 8.53 s | 15.0 tok/s | 13.11 GB | 5.95 GB |
| 4 | 8.70 s | 2.18 s | 58.8 tok/s | 13.59 GB | 5.52 GB |
| 8 | 11.61 s | 1.45 s | 88.2 tok/s | 14.36 GB | 4.88 GB |
| 16 | 17.60 s | 1.10 s | 116.3 tok/s | 15.60 GB | 3.83 GB |
| 逐个（LLMPipeline × 8） | 49.22 s | 6.15 s | 20.8 tok/s | 5.33 GB | 14.43 GB |

- 16 并发时最低可用内存 3.83 GB，未触发 3 GB 停止条件。
- 连续批处理 16 并发的吞吐是逐个跑的 5.6 倍；单请求延迟从 8.53 s 降到 1.10 s。
- 峰值 RSS 高是因为 `cache_size=8` 预分配 KV 缓存；逐个跑时只有 5.3 GB。

### 8.3 真实 prompt 质量（`quality_test.py`）

- judge 6 条（中英各 3；2 支持、2 数字不符、2 张冠李戴），extract 6 条（中英各 3）。
- 用产品里的 `judge._PROMPT` / `claims._PROMPT`，Pydantic `JudgeOut` / `_ClaimsOut` 校验。

| 指标 | 结果 |
| --- | --- |
| judge label 正确 | 6 / 6 |
| off_topic 标志正确 | 4 / 6（两条张冠李戴都判了 unsupported，但 `off_topic=false`） |
| extract JSON + schema | 6 / 6 |
| extract 逐字子串 | 3 / 6 |
| extract 规范化后子串 | 6 / 6 |
| `<think>` 泄漏 | 0 |

- 逐字失败的 3 条都是标记删除后的双空格（`COCO  and`、`Faster R-CNN  作为`、`批归一化  和`），用 `evidence.normalize_text` 后全部匹配；产品本身按规范化比较，不算错误。
- 质量结论：8B-int4 在 GPU 上 judge 标签 6/6，off_topic 标志需要提示词或复核层补强；extract 输出结构与原文定位都正常。

## 9. NPU 8B-cw（第 3 步）

### 9.1 编译缓存与加载

- `CACHE_DIR=C:\clover-models\.ov_cache_npu\len2048`，`MAX_PROMPT_LEN=2048`，`MIN_RESPONSE_LEN=256`。
- 冷编译（空缓存）：**45.33 s**；缓存后加载：**5.12 s**。
- `MAX_PROMPT_LEN=4096`：冷编译 **53.9 s**，缓存后加载 **4.74 s**，编译通过。
- 命令：

```powershell
.venv\Scripts\python ..\demo\intel\bench\npu_load_test.py `
  --model C:\clover-models\Qwen3-8B-int4-cw-ov `
  --cache-root C:\clover-models\.ov_cache_npu --max-prompt-len 2048 --timeout-s 1800 `
  --out ..\demo\intel\bench\npu-load-2048.json
```

- 与 1.7B 非对称 int4 对比：后者编译 40+ 分钟未完成；8B 对称逐通道 int4 45 秒完成。结论：NPU 的瓶颈是量化格式，不是 NPU 本身。

### 9.2 生成

```powershell
.venv\Scripts\python ..\demo\intel\bench\npu_runner.py --model C:\clover-models\Qwen3-8B-int4-cw-ov `
  --device NPU --cache C:\clover-models\.ov_cache_npu\len2048 --max-prompt-len 2048 `
  --mode gen --max-new-tokens 128 --out ..\demo\intel\bench\npu-gen-2048.json
```

| 指标 | 结果 |
| --- | --- |
| prompt | 1315 token |
| TTFT | 2.73 s |
| decode | 18.55 tok/s |
| 生成 128 token 总耗时 | 9.63 s |
| `<think>` | 无 |

- 第一次用 `apply_chat_template(extra_context={"enable_thinking": False})` 生成原始 prompt，输出仍带 `<think>`；改用 `ChatHistory.set_extra_context` 后关闭成功。
- 另一次失败：prompt 2362 token 超过 `MAX_PROMPT_LEN=2048`，报错 `2362 is passed. Set the "MAX_PROMPT_LEN" config option to increase the limit`；把 prompt 压到 1315 token 后正常。

### 9.3 NPU 质量（8B-cw）

| 指标 | GPU 8B | NPU 8B-cw |
| --- | ---: | ---: |
| judge label 正确 | 6 / 6 | 5 / 6 |
| off_topic 标志正确 | 4 / 6 | 4 / 6 |
| extract JSON + schema | 6 / 6 | 6 / 6 |
| extract 规范化后子串 | 6 / 6 | 4 / 6 |
| `<think>` 泄漏 | 0 | 0 |

- NPU 的 judge 错误：`en_numeric_mismatch` 把“50 fps”与原文“5 fps”判成 supported。
- NPU 的 extract 两条问题：`en_1` 的 claim 跨过标记后没带逗号，`zh_2` 把同一句拆成两条不连续的 claim（“批归一化 使得…” / “残差连接 使得…”），按产品规则会回退到整句。
- NPU 单次 judge 延迟 5.28–7.35 s，extract 3.47–5.31 s，比 GPU 的 3.9–5.9 s / 2.3–3.3 s 慢，且精度有可见下降。

### 9.4 组合负载（`combo_test.py`）

三个工作线程同时跑 180 s：GPU 8B judge、NPU 8B-cw extract、NPU Embedding（每次 24 窗口）。

| 任务 | 单独 | 组合 | 变慢 |
| --- | ---: | ---: | ---: |
| GPU 8B judge | 4.26 s/次，0.235 次/s | 6.08 s/次，0.165 次/s | 1.42× |
| NPU extract | 4.13 s/次，0.242 次/s | 12.97 s/次，0.077 次/s | 3.14× |
| NPU 向量（24 窗口） | 1.55 s/批 | 5.06 s/批 | 3.26× |

- 组合峰值 RSS 11.76 GB，最低可用内存 7.41 GB。
- 无热降频迹象：judge 前/后半段 0.165 / 0.164 次/s，extract 0.077 / 0.077 次/s。
- 说明：组合脚本里的「solo embed」段被已加载的 NPU 8B-cw 拖慢（平均 67 s/批），不是干净基线；干净基线用 `embed_solo_test.py` 单独测得 1.55 s/批（10 次 1.48–1.78 s）。上表的 3.26× 用干净基线计算。
- 结论：NPU 上 extract 与向量互相抢设备，各慢约 3 倍；GPU judge 只慢 42%。如果按推荐分工（GPU judge + NPU extract/向量），需要接受 NPU 内部两项的互相拖慢。

## 10. 同步 master 与 FastAPI lifespan

```powershell
git fetch cn
git merge cn/master        # fast-forward 到 2f39c40
cd backend
uv sync --extra dev --extra intel
uv pip install psutil huggingface_hub   # 基准脚本需要
```

- master 变更：`server.py` 的 startup 改为 lifespan；`Onboarding.tsx` 的平台文案。
- 仓库没有 `uv.lock`，`uv sync` 直接解析 71 个包：FastAPI 0.162.0、Starlette 1.10.0。
- 移除之前 venv 里的 `fastapi<0.116` 固定。
- pytest：**500 passed, 2 failed, 8 skipped in 300.59s**（FastAPI 的收集错误已消失）。
  - 仍失败：`test_parse_latex.py::test_tables_become_cell_paragraphs`、`test_pipeline.py::test_library_scan_reports_stages`（缺 PDF）。

## 11. LaTeX 测试失败的根因：CRLF

```powershell
.venv\Scripts\python -m pytest tests/test_parse_latex.py::test_tables_become_cell_paragraphs -vv
```

失败断言：

```text
lm = d.latex
big = next(p for p in d.paragraphs if p.text == "EN-FR")
f, off, exact = lm.locate(big.id, 0)
src = (tmp_path / "main.tex").read_text()
assert exact and src[off:off + 5] == "EN-FR"
E   AssertionError: assert (True and '\\midr' == 'EN-FR')
```

`git ls-files --eol backend/tests/fixtures` 中 LaTeX 相关行全部是 `i/lf w/lf`：

```text
i/lf w/lf attr/text=auto eol=lf  backend/tests/fixtures/latex_authoryear.tex
i/lf w/lf attr/text=auto eol=lf  backend/tests/fixtures/latex_numeric/main.tex
i/lf w/lf attr/text=auto eol=lf  backend/tests/fixtures/latex_numeric/method.tex
i/lf w/lf attr/text=auto eol=lf  backend/tests/fixtures/latex_numeric/refs.bib
```

对照实验（`diag_latex_eol.py`，同一段 TeX）：

```text
LF (newline='')  bytes_has_CRLF=False  off=227  slice='EN-FR'  exact=True
CRLF (default)   bytes_has_CRLF=True   off=236  slice='\\midr'  exact=True
```

- 测试用 `Path.write_text()` 写临时 `main.tex`，Windows 默认把 `\n` 转成 `\r\n`。
- 解析器的 `tex.read_text()` 是 `path.read_bytes().decode()`，**保留 CRLF**，偏移按 2 字节换行计算。
- 测试随后用 `Path.read_text()` 读回，通用换行把 CRLF 归一成 LF，字符串变短，`off` 就落到后面的 `\midrule` 上。
- 偏移差 9，正好等于该位置之前的换行数。Mac 上 `os.linesep` 是 `\n`，所以通过。
- 未改产品代码；修法应是测试写入时 `newline=""`，或解析器/测试统一换行归一。

## 12. Qwen3.5 放弃与 Qwen3-4B 加载失败

### Qwen3.5

- `Qwen3.5-9B-int4-ov` 是 `Qwen3_5ForConditionalGeneration`（VLM）复合 IR：language_model + text_embeddings + vision_embeddings + mtp。
- `LLMPipeline` 加载后生成报：
  `RuntimeError: ... Port for tensor name input_ids was not found.`
- `VLMPipeline` 能加载（GPU 30.7 s），`generate(prompt, [], cfg)` 能出文本，但输出带 `Thinking Process:`，没有可用的关闭 thinking 路径。
- 按要求放弃 Qwen3.5；停止 Qwen3.5-4B 下载；9B 文件保留在磁盘，不再参与测试。

### Qwen3-4B

- 下载完成，sha256 与 HF LFS 一致（`openvino_model.bin` 2158.8 MB、`openvino_tokenizer.bin` 5.3 MB）。
- GPU 和 CPU 加载都失败，错误相同：

```text
Check 'false' failed at src/core/shape_inference/include/reshape_shape_inference.hpp:210:
While validating node 'opset1::Reshape Reshape_295
(opset1::Multiply self.model.layers.0.mlp.down_proj.weight/fq_weights_1[0]:f16[2560,76,128],
 opset1::Constant Constant_209892[0]:i64[2]) -> ()' with friendly_name 'Reshape_295':
Output pattern dim[1] has invalid bounds: -3891109803858067456,-3891109803858067456
```

- 版本：OpenVINO 2026.4.1 / openvino-genai 2026.4.1.0。未升级（等指示）。
- 因此 4B 的 batch/quality 无法执行，GPU/CPU probe 均记为失败。
