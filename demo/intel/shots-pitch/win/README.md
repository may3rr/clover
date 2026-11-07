# Windows 版路演截图（应用自带 shots 模式）

2026-11-07 在 Intel 决赛机上重拍。Windows 11（26200），Intel Core Ultra 5 338H / Arc B370，
屏幕 2560 × 1600，**显示缩放 200%**，浅色主题。代码合并到 `cn/master` 的 `898b7f2`。

- 报告数据：`app/site/public/data/pitch_zh.json`（《基于深度学习的目标检测研究综述》）。
- 状态固定为 `running-mid,report,item:f40,item:f28,item:v5,venue:f35`，主题只拍 `light`。
- Windows 上没有 `screencapture`，截图走 Electron `capturePage`（`run.log` 末尾
  `SHOTS_METHOD page`），所以图里没有系统最小化/最大化/关闭按钮，窗口是应用默认大小
  （CSS 1279 × 752，像素 2558 × 1504），没有最大化。
- `venue:f35` 会先把正文滚到“电子学报 对标”卡片，再打开右侧 f35 详情；主进程为此多等 1.2 秒。

## 文件

| 文件 | 状态 | 画面 |
| --- | --- | --- |
| `light-running-mid.png` | `running-mid` | 运行页，44%。文献真实性已完成（3 个问题），引用分布已完成（3 个问题），论断支持度进行中，格式规范等待。 |
| `light-report.png` | `report` | 报告页总览：43 个问题、9 项修订；引用标记 96 处、参考文献 73 条、检查用时 22 秒，属性里有“发往云端 80,689 字”。 |
| `light-item-f40.png` | `item:f40` | 详情“未能在数据库中找到这篇文献”：Crossref、OpenAlex、arXiv 均未检索到 [70] 的题录。 |
| `light-item-f28.png` | `item:f28` | 详情“被引文献与这条论断说的不是同一项工作，可能引错了文献”：正文说 CornerNet 借鉴 [40] 的关键点检测思想，[40] 实际是 Attention Is All You Need。 |
| `light-item-v5.png` | `item:v5` | 详情“建议修订：制 改为 置”：NMS 段落“分类制置信度排序”的原文、修订对照。 |
| `light-venue-f35.png` | `venue:f35` | 画面中间是“电子学报 对标”评审卡片（实验规模、分析深度、文献覆盖、引用可靠性、结构完整，以及对标的 3 篇论文），右侧是 f35“参考文献构成偏离《电子学报》范文的常见范围”的详情。 |

`light-empty.png` 是 11 月 6 日那一轮拍的首页，本轮的 STATES 不含 `empty`，没有重拍，保留备用。

## SHOT_CHECK 原文（run.log 第 46–56 行）

```text
SHOT_CHECK running-mid => (no detail open)
SHOT_CHECK report => (no detail open)
SHOT_CHECK item:f40 => 全部问题 | 未能在数据库中找到这篇文献
SHOT_CHECK item:f28 => 全部问题 | 被引文献与这条论断说的不是同一项工作，可能引错了文献
SHOT_CHECK item:v5 => 全部问题 | 建议修订：制 改为 置
SHOT_CHECK venue:f35 => 全部问题 | 参考文献构成偏离《电子学报》范文的常见范围
```

最后四行与要求逐字一致；`running-mid`、`report` 本来就没有详情页，所以是 `(no detail open)`。

## 核对

- 六张图都已逐张打开：右侧详情（或 `venue:f35` 的评审卡片 + 详情）与上表一致。
- 画面里没有 API Key，也没有用户名路径；报告页只显示文件名，不显示完整路径。
- 左下角“李明”是 `lib/shots.ts` 的 `SAMPLE_PREFS` 示例资料；“最近检查”是
  `lib/useReports.ts` 的 `SHOT_HISTORY`，shots 模式固定的演示数据，不是本机真实检查记录。
- 旧的 `light-item-f35.png` 已删除，由 `light-venue-f35.png` 取代。
- 6 张新图单文件最大 864 KB（`light-item-f28.png`），均小于 10 MB。
