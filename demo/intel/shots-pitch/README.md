# Intel 三颗芯截图（PPT 用）

浅色模式，Clover 与任务管理器都用默认窗口大小（未最大化）。任务管理器在“性能”页，GPU 的引擎下拉为 **Compute**。

**关于“同时占用”的说明**：隐私模式下，本地 8B 的生成阶段（typo/extract/structure/function）和 NPU 的向量阶段在时间上基本错开——8B 在 GPU 上跑完时，NPU 向量还没开始。所以没有一张 GPU Compute 和 NPU 都到 90% 的图；下面用同一轮的两个阶段说明：

- `01-taskmanager-active.png`：向量阶段的同屏图，NPU 94%、GPU Compute 6% 的重排曲线、CPU 9%。
- `01b-taskmanager-gpu8b.png`：同一轮 8B 生成阶段，GPU Compute 98%、CPU 35%、NPU 0%。

两张合起来就是“三颗芯都在干活”，也正好对应路演里“各干所长、分时复用”的说法。

## 图

- `01-taskmanager-active.png`：隐私模式向量阶段，NPU 94%、GPU Compute 6%（重排）、CPU 9%，任务管理器左侧同时列出 CPU / NPU / GPU 三项。
- `01b-taskmanager-gpu8b.png`：同一轮本地 8B 生成阶段，GPU Compute 98%、CPU 35%、NPU 0%，说明 GPU 的 Compute 占用来自 Clover 的 Qwen3-8B。
- `02-clover-running.png`：Clover 运行页，标题左侧是千问变英特尔的 logo 动画，进度 85%（判定论断 52/109 对）。
- `03-taskmanager-idle.png`：空闲对照，模型已加载但没有任务，GPU Compute 1%、NPU 0%、CPU 15%，用来证明前两张的占用不是系统背景。
- `04-settings-privacy.png`：设置 › 模型 › 隐私模式开关打开的状态。
- `05-send-list.png`：隐私模式报告的“发往云端”展开：正文 11,700 字，发往云端 701,845 字；其中出自稿件的文字 5,910 字，只有 54 句带引用的论断、98 段被引片段和 55 条参考文献，稿件正文本身 0 字。
- `06-gpu-vector.png`：推荐配置（抽取回云端，隐私模式关闭）下核显跑向量，GPU Compute 97%、NPU 0%、CPU 19%。

## 现场状态

- 应用用推荐配置 `C:\clover-data\shots\c-home` + 空缓存 `C:\clover-data\shots\ready.sqlite` 启动，停在首页，可直接拖入 docx / LaTeX 压缩包开始体检。
- 任务管理器保持“性能 → GPU → Compute”，并已勾选“置于顶层”，评委可现场复核。
