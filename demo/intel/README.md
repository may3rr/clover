# Intel 机器上的 Clover：准备与验证

决赛要求在组委会的 Intel 电脑上本地运行至少一项 AI 能力。本目录是赛前准备：一份可行性脚本和这份操作手册。方案与端云边界见 `design/Intel本地化移植方案.md`。

## 1. 本地跑什么

| 能力 | 模型目录 | 产品里的位置 | 回退 |
| --- | --- | --- | --- |
| 被引原文向量检索 | `Qwen3-Embedding-0.6B-int8-ov` | `llm/embed.py`，`[llm.embedding] backend = "openvino"` | 加载失败时只用 BM25 |
| 候选片段重排 | `Qwen3-Reranker-0.6B-int8-ov` | `llm/rerank.py`，`[llm.rerank] backend = "openvino"` | 保留融合排序 |
| 论断抽取 | `Qwen3-1.7B-int4-sym-ov`（NPU）或 `Qwen3-1.7B-int4-ov`（GPU、CPU） | `llm/local.py`，`[llm.local] engine = "openvino"` | 回落云端 |

设备按 `device = "NPU,GPU,CPU"` 从左到右尝试，第一个编译成功的被采用。三个模型的 OpenVINO 实现都在 `llm/ov.py`。

NPU 的两条限制：

- 向量模型用末位池化加左侧补齐，NPU 上必须固定形状：每次一个窗口，补齐到 `max_length`（默认 512）。
- 大模型在 NPU 上只认对称量化的 int4。OpenVINO 官方的 `Qwen3-1.7B-int4-ov` 是非对称 group 128，在 NPU 上大概率编译不过，会自动落到核显。要上 NPU，用第 4 节导出的 `int4-sym` 版本。

## 2. 在 Mac 上的实测（2026-11-03，M3 Pro，只有 CPU）

| 项 | 结果 |
| --- | --- |
| 向量：冷加载 / 缓存后加载 | 6.7 s / 0.8 s |
| 向量：24 个窗口 / 3 条查询 | 1.38 s / 0.23 s，三条查询的首选全部正确 |
| 重排：冷加载 | 9.1 s |
| 重排：6 个候选 / 24 个候选 | 1.25 s / 4.73 s，正确片段得分 0.9995 |
| 1.7B 抽取（官方 int4 非对称）：冷加载 / 每句 | 20.4 s / 2.0 到 3.4 s，JSON 全部可解析；中文句漏掉了一个标记 |
| 1.7B 抽取（自己导出的 int4 对称逐通道，NPU 用）：冷加载 / 每句 | 14.8 s / 4.2 到 8.8 s；英文句正确，中文句输出不符合格式，还编出了不存在的标记 m3 |
| 产品检索链路 | BM25、本地向量、本地重排融合后，「每秒 50 帧」的论断取到了写着「每秒 5 帧」的原文 |

对称逐通道量化把全部权重压到 4 位，1.7B 的抽取质量明显下降，NPU 上的抽取不宜用 1.7B。可选的退路：NPU 只跑向量和重排，抽取放在核显上跑官方 int4 版本；或者导出 4B 的对称版本再测（Mac 内存只有 18GB，4B 留到实验室机器上导出）。

按这个速度，Mac CPU 上一篇演示稿约 6000 个窗口要算 6 分钟左右的向量，比云端冷启动慢。到 Intel 机器上要测的就是 NPU 和核显能快多少；如果不够快，再加「先用 BM25 预选候选窗口，只给候选算向量」。

## 3. Windows 机器上的步骤

前提：Windows 11，酷睿 Ultra（带 NPU），已装最新的 Intel 显卡驱动和 NPU 驱动。

```powershell
# 1. Python 3.11 与 Node 20（官网安装包，勾选加入 PATH）
python --version; node --version

# 2. 后端
cd clover\backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,intel]"

# 3. 模型：从 U 盘拷到 D:\clover-models（四个目录，见第 1 节）

# 4. 可行性验证（不需要 API Key）
.venv\Scripts\python ..\demo\intel\probe.py --models D:\clover-models --out ..\demo\intel\probe-finals.json
# NPU 版抽取模型另跑一次
.venv\Scripts\python ..\demo\intel\probe.py --models D:\clover-models --llm Qwen3-1.7B-int4-sym-ov --only llm --out ..\demo\intel\probe-finals-npu-llm.json

# 5. 配置：复制 config.example.toml 为 config.toml，改下面几段
#    [llm.local]     enabled = true, engine = "openvino", model = "D:/clover-models/Qwen3-1.7B-int4-sym-ov"
#    [llm.embedding] enabled = true, backend = "openvino", local_model = "D:/clover-models/Qwen3-Embedding-0.6B-int8-ov"
#    [llm.rerank]    enabled = true, backend = "openvino", local_model = "D:/clover-models/Qwen3-Reranker-0.6B-int8-ov"
#    .env 里放 DASHSCOPE_API_KEY（支持度判断仍走云端 Qwen）

# 6. 测试与前端
.venv\Scripts\python -m pytest -q
cd ..\app; npm ci; npm run dev
```

开发模式下，主进程会自动找 `backend\.venv\Scripts\python.exe`；也可以用环境变量 `CITECHECK_PYTHON` 指定。

## 4. 导出 NPU 用的对称 int4 模型

在 Mac 或实验室机器上做，需要 `optimum-intel[openvino]` 和 `nncf`：

```bash
optimum-cli export openvino -m <Qwen3-1.7B 目录或 Qwen/Qwen3-1.7B> \
    --weight-format int4 --sym --ratio 1.0 --group-size -1 Qwen3-1.7B-int4-sym-ov
```

## 5. 要记下的数（填进路演的「48 小时变化」表）

- `probe.py` 输出里每个设备的 `ok`、冷加载、缓存后加载、单次耗时，以及向量的 `cos_vs_cpu_min`（NPU 结果与 CPU 的最小余弦，OpenVINO 自己的测试里 Qwen3 向量在 NPU 上误差偏大，要看这个数）。
- 断网后完整跑一遍演示稿，确认本地三项照常运行，并记下云端那部分（支持度判断、真实性检索）在断网时报告里怎么呈现。这一项还没验证过。
- `demo/testset/profile_cost_speed.py` 的冷启动墙钟和单篇花费，与 `PRE_HACKATHON_BASELINE.md` 第 2 节对照。
