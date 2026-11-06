# 11 月 7 日：Intel 决赛机上的截图、录屏与提交前检查

> 给 Intel 决赛机上的 agent。仓库在 `C:\clover`。17:00 前用户要把完整文件包上传群文件，按顺序做，每一步做完在 `demo/intel/shots-pitch/win/README.md` 记一行结果。

## 1. 同步代码

```powershell
cd C:\clover
git fetch cn
git merge cn/master
```

有冲突就停下来告诉用户，不要自己选一边。合并后跑 `backend` 的 pytest，在 `app` 下 `npm install`，再启动应用确认能打开。

合并进来的修复：知网 PDF 字宽表是间接对象时读不出文字；期刊对标的参考文献构成批注被并进章节分组；截图模式可以载入指定报告、只拍指定状态。

## 2. 准备

1. 用户用 U 盘拷来三篇《电子学报》2026 年综述（作者沈蒙、王静、杨杰），放进 `C:\clover\demo\final\演示稿\ref\`。PDF 不提交。
2. 安装 `天猫Ai黑客松｜选手路演PPT模版\字体包` 里的全部字体（右键，为所有用户安装）。
3. 显示缩放设为 200%，电源插上，电源模式设为最佳性能。

## 3. 截图：路演 PPT 里的软件窗口

截图模式载入路演用的同一份报告，按编号直接打开要拍的问题，不重新体检，结果不会因为网络变化。

```powershell
cd C:\clover\app
$env:CITECHECK_SHOTS_REPORT = "C:\clover\app\site\public\data\pitch_zh.json"
$env:CITECHECK_SHOTS_STATES = "running-mid,report,item:f40,item:f28,item:v5,item:f35"
$env:CITECHECK_SHOTS_THEMES = "light"
node scripts\shots.mjs C:\clover\demo\intel\shots-pitch\win 2>&1 | Tee-Object C:\clover\demo\intel\shots-pitch\win\run.log
```

核对 `run.log` 里的 `SHOT_CHECK` 行，最后四行必须分别包含：

| 状态 | 打开的问题 |
| --- | --- |
| item:f40 | 未能在数据库中找到这篇文献 |
| item:f28 | 被引文献与这条论断说的不是同一项工作 |
| item:v5 | 建议修订：制 改为 置 |
| item:f35 | 参考文献构成偏离《电子学报》范文的常见范围 |

对不上或写着 `(no detail open)` 就停下来，把 `run.log` 原文发给用户。

逐张打开图片检查：

- 右侧打开的详情是上表那一条；
- 没有 API Key、用户名路径；
- 左侧最近检查列表可以公开，不确定就问用户。

截图模式截的是网页内容，系统画的最小化、最大化、关闭按钮不在图里，这是正常的，不要自己补画。

## 4. 录屏：真实运行

用推荐配置（向量与重排在核显，其余走云端）、清空的缓存，真实跑一遍演示稿，用 Xbox Game Bar（Win+Alt+R）或 OBS 录整个屏幕，1080p 以上：

1. 首页填目标期刊「电子学报」，拖入 `demo\final\演示稿\基于深度学习的目标检测研究综述.docx` 和它的 `ref` 文件夹；
2. 连接确认页，对标范文默认勾选三篇综述；
3. 运行页，中途切到任务管理器性能页，GPU 引擎切到 Compute，停 10 秒；
4. 报告页，依次打开上表四条问题；
5. 导出到 Word，在 Word 里看批注和修订；
6. 设置页打开隐私模式，看说明文字；回到报告，展开发往云端一行看发送清单。

外部检索被限流时 [70] 可能显示暂时无法核验，照实录下来，不要换文献。视频存为 `效率进化赛道-我要发顶刊-Clover-演示视频.mp4`，大于 10MB 不提交 git，直接交给用户。

## 5. PPT 检查与 PDF

1. 用 PowerPoint 打开用户给的 `效率进化赛道-我要发顶刊-Clover.pptx`，逐页看字体是否是阿里巴巴普惠体、有没有文字溢出或错位，有问题截图告诉用户。
2. 文件，另存为 PDF，文件名不变，交给用户替换 Mac 上导出的那份。

## 6. 提交

截图、`run.log` 和 `README.md` 提交到 `intel` 分支，`git push cn intel`。不要推 `master`，不要 `--force`。告诉用户已推送，Mac 上会用这些截图重新生成 PPT。
