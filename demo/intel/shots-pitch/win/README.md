# Windows 版路演截图（应用自带 shots 模式）

2026-11-06 在 Intel 决赛机上拍摄。Windows 11（26200），Intel Core Ultra 5 338H / Arc B370，
屏幕 2560 × 1600，**显示缩放 200%**，浅色主题。

- 报告数据：`app/site/public/data/pitch_zh.json`（《基于深度学习的目标检测研究综述》）。
- 拍摄方式：按任务给的环境变量跑 `node scripts\shots.mjs`，状态固定为
  `empty,running-mid,report,item:f40,item:f28,item:v5,item:f35`，主题只拍 `light`。
- Windows 上没有 `screencapture`，截图走 Electron `capturePage`（`run.log` 末尾
  `SHOTS_METHOD page`），所以图里没有系统标题栏，窗口是应用默认大小（CSS 1279 × 752，
  像素 2558 × 1504），没有最大化。

## 文件

| 文件 | 状态 | 画面 |
| --- | --- | --- |
| `light-empty.png` | `empty` | 首页空状态。左侧“最近检查”是 shots 模式内置的演示历史（`numeric_en.docx`、`hallucination_survey.docx`、`retrieval_paper.docx`），中间是拖入区，右侧是四项检查说明。 |
| `light-running-mid.png` | `running-mid` | 运行页，44%。文献真实性已完成（5 个问题），引用分布已完成（7 个问题），论断支持度进行中，格式规范等待。 |
| `light-report.png` | `report` | 报告页总览：43 个问题、9 项修订；引用标记 96 处、参考文献 73 条、检查用时 22 秒，属性里有“发往云端 80,689 字”。 |
| `light-item-f40.png` | `item:f40` | 详情“未能在数据库中找到这篇文献”：Crossref、OpenAlex、arXiv 均未检索到 [70] 的题录。 |
| `light-item-f28.png` | `item:f28` | 详情“被引文献与这条论断说的不是同一项工作，可能引错了文献”：正文说 CornerNet 借鉴 [40] 的关键点检测思想，[40] 实际是 Attention Is All You Need。 |
| `light-item-v5.png` | `item:v5` | 详情“建议修订：制 改为 置”：NMS 段落“分类制置信度排序”的原文、修订对照。 |
| `light-item-f35.png` | `item:f35` | 详情“参考文献构成偏离《电子学报》范文的常见范围”：近三年占比、外文占比、年龄中位数等六项与范文区间，对标 3 篇。 |

## SHOT_CHECK 原文（run.log 第 46–58 行）

```text
SHOT_CHECK empty => (no detail open)
SHOT_CHECK running-mid => (no detail open)
SHOT_CHECK report => (no detail open)
SHOT_CHECK item:f40 => 全部问题 | 未能在数据库中找到这篇文献
SHOT_CHECK item:f28 => 全部问题 | 被引文献与这条论断说的不是同一项工作，可能引错了文献
SHOT_CHECK item:v5 => 全部问题 | 建议修订：制 改为 置
SHOT_CHECK item:f35 => 全部问题 | 参考文献构成偏离《电子学报》范文的常见范围
```

最后四行与任务给的四条标题逐字一致；`empty`、`running-mid`、`report` 三个状态本来就没有详情页，
所以是 `(no detail open)`。

## 核对

- 四张详情图右侧打开的详情就是上表对应的那一条，已逐张看过。
- 画面里没有 API Key，也没有用户名路径；报告页只显示文件名，不显示完整路径。
- 左下角“李明”是 `lib/shots.ts` 里的 `SAMPLE_PREFS` 示例资料；“最近检查”是
  `lib/useReports.ts` 的 `SHOT_HISTORY`，shots 模式固定的演示数据，不是本机真实检查记录。
- `run.log` 是这次运行的完整输出（PowerShell `Tee-Object`，为方便跨平台查看已转成 UTF-8）。
- 7 张 PNG 单文件最大 904 KB（`light-item-f28.png`）；`run.log` 2.9 KB，均小于 10 MB。
