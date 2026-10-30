# Clover 界面细节打磨：调研结论与实现计划

2026-10-29。本轮只做调研和设计，没有改动 `app/` 下的任何代码。

配套演示：[demo.html](demo.html)，八页，每页一个组件，用 tokens.css 的配色，跟随系统深浅色。在 Clover 的 Electron 窗口或 Claude 桌面端的浏览器面板里打开效果最准，这两处都能渲染 `-electron-corner-smoothing`。

| 页 | 组件 | 对应任务 |
| --- | --- | --- |
| 1 | 期刊对标占位卡，运行页期刊评审行 | F28、F29 |
| 2 | 三点轨道等待指示 | F28 |
| 3 | 缓动曲线家族 | F25 |
| 4 | 循环动效与停滞进度 | F25、F28 |
| 5 | 连续圆角与同心圆角 | F27 |
| 6 | 落点高亮 | F30 |
| 7 | 浮层出场 | F30 |
| 8 | 中英混排行高、自动间距、标题断行、光学居中 | F26 |

---

## 1. 结论摘要

1. 现有的 `--ease: cubic-bezier(0.2, 0.8, 0.2, 1)` 作为进入和响应曲线没有问题，问题在于它被用在所有场合。往复循环、窗格平移和视图过渡需要别的曲线；视图过渡现在实际走的是浏览器默认的 `ease`，和站内其他动效不是一套。建议加三条 token：`--ease-drawer`、`--ease-sine`、`--spring`，见第 3.1 节。
2. 超椭圆适用于我们，但不建议用标准的 `corner-shape: squircle`。我们是 Electron 44（Chromium 152），自带 `-electron-corner-smoothing: system-ui`，与 macOS 的连续圆角一致，边框、阴影、焦点环跟着变形，`border-radius` 的数值不用改。只用在 8px 及以上的面（卡片、浮层、列表选中行、输入框、插图），胶囊、圆形、正文高亮不动。见第 3.3 节。
3. 期刊对标慢，原因是 `pipeline.py` 在四层结束后才串行调用 `critique`，报告要等它返回才发 `done`。占位动效分两步：先改运行页那一行（纯前端加一个后端事件字段），再让报告先打开、对标后到（前后端都要改，需要你拍板）。占位卡只如实显示已经拿到的信息，不做假进度。见第 3.5 节。
4. 字号层级本身没问题，问题在行高。界面文字没有写行高，中文行比纯英文行高 7px（demo 第 8 页实测：同结构的列表行 52.5px 对 59.5px），还带出半像素高度。建议六档字号配固定行高，见第 3.6 节。
5. 我没有找到 Claude 新动画的公开资料，三点轨道是按你的描述从投影原理做的：倾斜圆盘、透视缩放、深度决定透明度和遮挡顺序。参数可以在 demo 第 2 页调。

---

## 2. 调研来源

| 来源 | 用到的内容 |
| --- | --- |
| [Apple HIG：Motion](https://developer.apple.com/design/human-interface-guidelines/motion) | 动效要短而准；不要让人反复等待不必要的动效；减少动态效果时减弱或去掉动画 |
| WWDC18《Designing Fluid Interfaces》，经 [Nathan Gitter 的整理](https://medium.com/@nathangitter/building-fluid-interfaces-ios-swift-9732bb934bf5) | 弹簧用阻尼比和响应两个参数描述；动画可打断、可改向；从当前呈现值出发 |
| [emilkowalski/skills](https://github.com/emilkowalski/skills)（`emil-design-eng/SKILL.md`） | 进入退出用 ease-out，屏内移动用 ease-in-out，不用 ease-in；按使用频率决定是否动画，键盘触发的操作不动画；按压缩放 0.95 到 0.98；浮层从触发点缩放；连续触发用 transition 不用 keyframes；退出比进入快 |
| [Vercel Web Interface Guidelines](https://vercel.com/design/guidelines) | 加载态先延迟约 150–300ms 再出现、出现后至少停留约 300–500ms；骨架与最终内容同形；同心圆角；不用 `transition: all`；±1px 光学校正 |
| [Jakub Krehel：make-interfaces-feel-better](https://www.ui-skills.com/skills/jakubkrehel/make-interfaces-feel-better) | 外半径等于内半径加间距；标题 `text-wrap: balance`；图标切换用缩放、透明度和 4px 模糊；按压不低于 0.95 |
| [Electron RFC 0012：corner smoothing](https://github.com/electron/rfcs/blob/main/text/0012-corner-smoothing.md) | `-electron-corner-smoothing` 的语法、`system-ui` 取值、对边框阴影描边的影响 |
| [Frontend Masters：corner-shape 与超椭圆](https://blog.master.dev/understanding-css-corner-shape-and-the-power-of-the-superellipse/)，[Chrome：实现 corner-shape](https://developer.chrome.com/blog/implementing-corner-shape)，[Figma：Desperately seeking squircles](https://www.figma.com/blog/desperately-seeking-squircles/) | `superellipse(k)` 的指数含义；Blink 对阴影和描边的处理；Figma 的 iOS 预设是 60% 平滑 |
| [Chrome：linear() 缓动](https://developer.chrome.com/docs/css-ui/css-linear-easing-function) | 用 `linear()` 把弹簧写成纯 CSS 曲线 |
| [Chrome：text-box-trim](https://developer.chrome.com/blog/css-text-box-trim)，[Chrome：CSS 国际化新特性](https://developer.chrome.com/blog/css-i18n-features) | 按大写字母高度裁切行框；`text-autospace` 与 `text-spacing-trim` |

本机核对：`node_modules/electron` 为 44.4.5，内置 Chromium 152.0.7977.130。框架二进制里能找到 `-electron-corner-smoothing`、`corner-shape`、`text-box-trim`、`text-autospace`、`interpolate-size`、`@starting-style`、`sibling-index`、`scroll-state` 的实现，上面提到的特性都能直接用。

---

## 3. 设计决定

### 3.1 缓动 token

在 `tokens.css` 里保留 `--ease`，新增三条：

```css
--ease-out: var(--ease);                         /* 进入、响应、hover、颜色变化 */
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);   /* 窗格折叠、抽屉、屏内位移 */
--ease-sine: cubic-bezier(0.37, 0, 0.63, 1);     /* 往复循环：呼吸、漂浮、微光 */
--spring: linear(0, 0.019, 0.068, 0.136, 0.216, 0.302, 0.389, 0.473, 0.553,
  0.626, 0.693, 0.751, 0.802, 0.846, 0.883, 0.914, 0.94, 0.96, 0.976, 0.989,
  0.998, 1.005, 1.009, 1.013, 1.014, 1.015, 1.015, 1.015, 1.014, 1.012, 1.011,
  1.01, 1.009, 1.007, 1.006, 1.005, 1.004, 1.003, 1.003, 1.002, 1);
--spring-dur: 520ms;
```

`--spring` 由阻尼比 0.8、响应 0.4s 的弹簧采样 40 段得到，过冲 1.5%，眼睛感到落定约在 300ms。它只用在“落定”类时刻：勾选画完、卡片换入、浮层展开、三点收拢后小球出现。

使用规则：

| 场合 | 曲线 | 时长 |
| --- | --- | --- |
| hover、颜色、按压 | `--ease-out` | 160ms（现在 120ms 和 160ms 混用，统一为 160ms） |
| 进入：行、卡片、详情 | `--ease-out` | 240ms |
| 退出 | `--ease-out` | 进入时长的约 0.6 倍，例如 240ms 进入配 140ms 退出 |
| 窗格折叠、屏内位移 | `--ease-drawer` | 240–320ms |
| 视图过渡 | `--ease-drawer`（位移），`--ease-out`（淡入淡出） | 360ms |
| 落定 | `--spring` | `--spring-dur` |
| 无限循环 | `--ease-sine` | 不变 |
| 匀速旋转 | `linear` | 不变 |

频率规则：一天几十次以上的操作（列表上下键、筛选切换）不做过渡或只做 opacity；键盘连续触发的操作不做 morph。

### 3.2 现有动效的具体问题

| # | 现象 | 位置 | 建议 |
| --- | --- | --- | --- |
| M1 | 视图过渡只设了时长，曲线是浏览器默认 `ease` | `base.css:1066` `::view-transition-group(*)` | 补 `animation-timing-function`，group 用 `--ease-drawer`，old/new 用 `--ease-out` |
| M2 | 按压缩放有两条冲突规则：0.98（`base.css:249`）和 0.97（`base.css:974`），后者覆盖前者，`icon-btn` 和 `side-tab` 仍是 0.98 | `base.css:239-250`、`966-975` | 合并为一条，统一 0.97 |
| M3 | 呼吸动画用 `--ease`，每段先快后慢，循环接缝处顿一下（demo 第 4 页有曲线图） | `base.css:1792` `cc-breathe` | 改 `--ease-sine`，幅度从 0.45 收到 0.55 |
| M4 | 骨架微光用 `linear`，像传送带 | `base.css:921` `cc-shimmer` | 改 `--ease-sine` |
| M5 | 落点高亮闪的是整段 opacity，正文一起变淡，读起来像告警 | `base.css:1498` `cc-flash`，`ReportScreen.tsx:312-317` | 只动底色加一圈 box-shadow 柔光，一次落定（demo 第 6 页） |
| M6 | 上下键浏览问题时，详情打开状态下每按一次都走一次 morph | `ReportScreen.tsx:383-390` | 键盘导航时直接切换，鼠标点开详情才 morph |
| M7 | 导出浮层只从上方 4px 淡入，退出没有动画 | `base.css:307-336` | `transform-origin: top right`，scale 0.96 到 1 走 `--spring`，退出 140ms（demo 第 7 页） |
| M8 | 引导页离开与进入同为 480ms | `base.css:1534-1538` | 离开改为 280ms |
| M9 | 列表行 stagger 在筛选切换时也会对新出现的行生效 | `ReportScreen.tsx:1057` | 只在报告首次打开时 stagger，可以改用 `sibling-index()` 写在 CSS 里 |
| M10 | 窗格折叠动画的是 `width` 和 `margin`，阅读区每帧重排整篇论文 | `base.css:439-489` | 先测帧率再决定，见 F31 |
| M11 | 减少动态效果时把所有动画时长压到 0.01ms，连 opacity 淡入淡出也没了 | `base.css:74-82` | 保留 opacity 和颜色过渡，只去掉位移、缩放和循环 |
| M12 | 滚到高亮用瞬时跳转 | `ReportScreen.tsx:311` | 一屏以内 smooth，超过一屏直接跳 |

### 3.3 连续圆角

结论：用，范围有限。

- 实现：`-electron-corner-smoothing: system-ui`。它与 macOS 的连续圆角一致，`border-radius` 数值不变，第 6.4 节的圆角表不用改。`corner-shape: squircle` 等于 `superellipse(2)`，比 macOS 更方，要配合放大半径才能接近（demo 第 5 页可以拖动指数和倍数对比），所以只作为官网 `app/site/` 的写法，并用 `@supports` 回退到普通圆角。
- 适用：卡片与详情卡（12px）、浮层（12px）、callout（8px）、列表行与侧栏行（8–10px）、输入框（8px）、论文插图与表格（8px）、骨架页（8px）。
- 不适用：胶囊按钮（980px，没有直边可平滑）、圆形头像和圆点、5px tile（20px 尺寸上看不出差别，可以加，但不作为验收项）、正文高亮（4px，内联且跨行）。
- 写法：在 `base.css` 里列一组选择器统一加，不散在组件里；组件内联 `borderRadius` 的几处（`OverviewCard.tsx:54`、`Running.tsx:241`）改为类名。

同心圆角：`.prov-addform`（12px，在 12px 卡片里，内边距 16px）和导出浮层里的行需要按“内半径 = 外半径 − 间距”核对。demo 第 5 页底部有对照。

### 3.4 三点轨道

用途：时长不定、要等模型返回的场合。期刊评审、支持度复核、范文细化。短等待继续用现有的转圈。

规格：

- 三个点在圆盘上等分 120°，圆盘倾角默认 24°（14px 尺寸用 32°），转速 0.45 圈/秒。
- 透视：投影系数 `f / (f − z)`，`f = 3R`。近处点更大，透明度从 0.3 到 1 随深度变化，z-index 按深度排序。
- 28px 及以上尺寸圆盘带 ±9° 的缓慢摆动，14px 关掉。
- 配色：默认取评审者粉 `--tile-pink`，与运行页的期刊评审小球一致。demo 里还有图层三色、墨色、强调蓝可选。
- 结束：半径在 240ms 内收拢到 0，同时交叉换入评审者小球（`--spring`）。
- 性能：rAF 只写 transform、opacity、z-index；IntersectionObserver 离屏停帧；`document.hidden` 时停帧。
- 减少动态效果：三点排成一行静止，只做依次明暗。
- 文件：`components/OrbitDots.tsx`，纯函数部分（投影计算）放 `lib/orbit.ts`，用 vitest 测深度排序和收拢。

### 3.5 期刊对标占位

现状链路：`pipeline.py:409-446`。`prepare`（挑范文、下载 PDF、读结构）与四层并行；四层结束后才 `critique`，然后才组装 Report 并发 `done`。运行页那一行在 critique 期间进度固定在 3% 并呼吸。

两步走：

第一步，运行页（F28）。

- 进度条：停滞时叠一道微光，不再固定 3%。
- 状态位：小号三点轨道替换转圈。
- 文字：写后端上报的真实阶段。`overview` 事件增加 `step` 字段，取值“正在获取近期论文”“正在读取 3 篇范文”“正在汇总评审意见”，分别对应 `pick_exemplars`、`read_one` 并发、`critique`。
- `meta.timings` 增加 `overview` 一项，以后可以量化这一段到底多慢。

第二步，报告先开（F29，需要你决定）。

- 后端：四层结束即组装 Report（`overview` 为 `{status: "pending"}`）、落库、发 `done`；critique 在同一个任务里继续，完成后更新 reports 表并在 SSE 上发 `overview` 事件，再发 `overview_done`。如果前端已经离开运行页，改为报告页订阅 `/jobs/{id}/events` 或者轮询 `/jobs/{id}/overview`。
- 前端：`OverviewCard` 增加 `pending` 状态，布局与最终卡片同形同高。标题行左侧是三点轨道，右侧“正在评审”；评语位三行微光；五个维度（实验规模、分析深度、文献覆盖、引用可靠性、结构完整）名称如实显示，档次位微光；“对标的近期论文”在 `prepare` 完成后就能拿到，如实逐条列出。
- 换入：三点收拢成小球，档次文字从 4px 模糊、0.96 缩放、透明换到清晰（240ms），评语换入，五个维度每行间隔 40ms 落定。卡片高度不变，阅读区不跳。
- 加载态时序：占位延迟 200ms 出现；出现后至少停留 400ms。
- 历史报告：落库时为 pending、之后进程退出的，重新打开时显示为 `unavailable`，文案“这次没有生成《…》对标。请重新体检以生成对标。”
- 导出：`backend/citecheck/export/` 不读 `overview`，对标结果不进 docx，导出不受影响。

### 3.6 字排

| 字号 | 行高 | 用途 |
| --- | --- | --- |
| 13 | 18 | 次要文字 |
| 15 | 22 | 界面文字 |
| 17 | 29（1.7） | 正文，现有 |
| 17 | 26 | 详情标题 |
| 20 | 28 | 章节标题 |
| 26 | 34 | 大标题 |
| 32 | 40 | 论文标题（现为 1.25，即 40） |

- 在 `tokens.css` 里加 `--lh-13` 等六个变量，`.t13` 等类同时设字号和行高，`body` 设 15/22。
- 图标与首行对齐：图标外包一个与行高等高的盒子并垂直居中，去掉 `marginTop: 1` 这类手调（`ReportScreen.tsx:1068` 等处）。同一行里混排 13px 和 15px 时用 `align-items: baseline`。
- `text-autospace: normal` 加在 `body` 上。现有手写空格保留，已有空格处不会重复加距。
- `text-wrap: balance` 加在 `.t26`、`.t32`、详情标题上。
- `text-box: trim-both cap alphabetic` 只用于纯英文或数字的小控件（版本号、计数徽标）。中文按钮裁切后会上浮，维持现状（demo 第 8 页红线对照）。
- `font-variant-numeric: tabular-nums` 现在全局开启，计数和百分比需要它；文献标识里的年份、标题里的数字用比例数字更自然。改为在计数、进度、用量表、表格上开启，`body` 不再全局设置。
- 字距：Apple 的系统字体在原生应用里按字号自动调整字距，Chromium 里是否同样生效我没能确认。F26 里先实测（同一词 13px 与 26px 的字宽比例），确认没有生效再考虑按 Apple 的字距表给 20px 以上的标题加负字距；确认生效就不动。

---

## 4. 实现任务

任务编号沿用 PLAN.md 的 F 序号。每个任务结束跑 `npm run typecheck && npm test && npm run lint:design`，涉及界面的再跑 `npm run shots` 对比截图，后端改动跑 `pytest`。

### F25 动效 token 与一致性

- `tokens.css`：加第 3.1 节的四个 token。
- `base.css`：M1、M2、M3、M4、M8、M11；hover 过渡统一 160ms。
- 不改任何组件结构，风险最低，可以最先做。
- 验收：`lint:design` 新增规则，组件和 base.css 里禁止出现 `cubic-bezier(` 与 `linear(` 字面量（tokens.css 除外），禁止 `ease`、`ease-in`、`ease-out` 关键字。

### F26 字排

- 第 3.6 节全部内容。
- 验收：在 vitest 之外加一个 shots 场景，检查器列表中英文条目行高一致；`lint:design` 禁止出现 `line-height: normal` 与没有配行高的字号类。

### F27 连续圆角

- 第 3.3 节；同步改 AGENTS.md 第 6.4 节，写明“8px 以上的面使用 `-electron-corner-smoothing: system-ui`”。
- 官网 `app/site/` 用 `corner-shape`，`@supports` 回退。
- 验收：shots 截图人工对比；焦点环跟随平滑形状。

### F28 三点轨道与运行页期刊评审行

- `components/OrbitDots.tsx`、`lib/orbit.ts` 与测试。
- `Running.tsx` 期刊评审行：微光、三点、阶段文字。
- 后端：`overview` 事件加 `step`；`meta.timings.overview`。
- 验收：vitest 覆盖投影与收拢；pytest 覆盖事件字段；减少动态效果下截图。

### F29 报告先开、期刊对标后到

- 依赖 F28。第 3.5 节第二步。
- 后端：`pipeline.py` 拆分 `done` 与 `overview_done`；reports 表支持更新 overview；`server.py` 的 SSE 在 `done` 后保持到 `overview_done`。
- 前端：`App.tsx` 在 `done` 后进入报告页并保持订阅；`OverviewCard.tsx` 增加 pending 与换入。
- 验收：pytest 模拟慢 critique，`done` 先于 `overview_done`；历史报告 pending 的回退；e2e 跑一遍导出。

### F30 交互细节

- M5、M6、M7、M9、M12。
- 验收：键盘上下键连按时不出现视图过渡；浮层快速连点能从当前状态折返。

### F31 窗格折叠性能（先测后改）

- 参照 `app/site/scripts/jank.mjs`，给应用写一个同样的测量：在一篇长论文上连续折叠展开左右窗格，记录掉帧和长帧。
- 如果掉帧明显，阅读区在动画期间固定为起始宽度、动画结束后一次重排；或改用视图过渡做窗格切换。不掉帧就不改。

### F32 设计规范落文

- 把第 3.1、3.3、3.6 节的规则写入 AGENTS.md 第 6 节（6.1 增加行高列，6.4 增加曲线表和连续圆角）。
- `lint:design` 的新增规则汇总说明。

建议顺序：F25 → F26 → F27 → F28 → F30 → F29 → F31 → F32。F25 到 F27 只动样式，可以一起做；F29 改动后端流程，放在三点组件稳定之后。

---

## 5. 需要你决定的事

1. F29 是否做。它让报告提前一到几十秒打开，代价是后端流程和落库逻辑变复杂，报告页要多处理一种“对标未完成”的状态。
2. 三点轨道的配色：评审者粉（与运行页小球一致，我的建议），还是图层三色或强调蓝。
3. 第 3 节的规则是否写进 AGENTS.md 第 6 节。写进去之后它们就是硬约束，后续任务都要遵守。
4. `tabular-nums` 从全局改为局部，会让界面上的年份和标题数字变为比例数字，这是可见变化。

## 6. 本轮不做的事

- 不引入 Framer Motion 等动画库，弹簧用 `linear()`，三点轨道用 rAF。
- 不改字号六档，不改配色。
- 不做 macOS 26 的玻璃材质：侧栏已经用原生 vibrancy，阅读区和检查器按第 6.3 节保持实底。
