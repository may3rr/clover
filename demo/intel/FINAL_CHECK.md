# 11 月 7 日 Intel 决赛机最终检查

执行时间：2026-11-07 14:00–15:10（UTC+8）。机器：HP OmniBook，Windows 11 26200，
Intel Core Ultra 5 338H / Arc B370，屏幕 2560 × 1600、显示缩放 200%。
仓库 `C:\clover`，分支 `intel`。

## 1. 代码与测试

- `git fetch cn`：`0b8efd5..86ba8f9  master -> cn/master`；`git merge cn/master` 为 fast-forward。
- 合并后 HEAD：`86ba8f9` — *Intel: final check prompt (sync check, import the Gu MRC report, verify in the app, restore the empty-cache setup)*。
- 是否包含 Mac 的 `5c071073`：是（`git merge-base --is-ancestor 5c071073 HEAD` 通过）。
- `backend`：`pytest -q` → **553 passed, 8 skipped**，用时 323.98 s。
- `app`：`npm run typecheck`（node / web / site 三个 tsc 项目）→ 无输出、退出码 0，**全部通过**。

## 2. 导入顾迎捷论文的报告

现场缓存库的确认依据：

- 用户级 / 机器级环境变量里都没有 `CITECHECK_HOME`、`CITECHECK_CACHE`。
- 现场启动脚本 `C:\clover-data\start_ready_app.cmd` 设置
  `CITECHECK_HOME=C:\clover-data\shots\c-home`、
  `CITECHECK_CACHE=C:\clover-data\shots\ready.sqlite`；运行中的 Clover 进程树确实是
  `cmd /c C:\clover-data\start_ready_app.cmd` 拉起的。
- `c-home\config.toml` 没有 `[cache] path`，所以缓存路径由 `CITECHECK_CACHE` 决定。

导入命令（`backend` 下，`CITECHECK_HOME` / `CITECHECK_CACHE` 按上面设置）输出：

```text
imported-d02a7ec2023720bca  基于神经网络的机器阅读理解综述  findings 64 {'high': 33, 'medium': 10, 'low': 21}  -> C:\clover-data\shots\ready.sqlite
```

导入后缓存库内容：`reports` 1 行、`kv` 仅 `prefs`、`vectors` 0 行、`llm_usage` 0 行 —
只有报告本身，没有任何模型判断的缓存。

## 3. 应用内核对

| # | 核对项 | 结果 | 截图 |
| --- | --- | --- | --- |
| 1 | 历史列表能看到这篇论文 | 通过 | `gu-01-history.png` |
| 2 | f43 判定与正文高亮、[100] 原文证据 | 通过 | `gu-02-f43.png` |
| 3 | 导出 Word：这一条是批注，错别字是修订 | 通过 | `gu-03-wps.png` |
| 4 | 插图正常显示 | 通过 | — |

1. **历史列表**：首页“最近检查”里有一条，显示为 `manuscript.docx`，今天 14:07，`33 条严重`。
   注意：列表按**文件名**显示，不是论文标题（`useReports` 用 `filename`），打开后报告页标题是
   《基于神经网络的机器阅读理解综述》。这是应用现有行为，不是导入出错。
2. **f43**：左侧筛到“论断支持度”（43 项），第 38 条正是「被引文献不支持这条论断」，
   引用 `[100] Xiong 等，2017，Dynamic Coattention Networks For Question Answering`。
   右侧详情里“你的论文写道”是“Xiong 等人[100]……HMN 模块可以使模型在 SQuAD1.1 数据集上的
   F1 值提高 5.5%”；正文同段落整段高亮；“被引文献原文”标红“不支持”，证据为
   “...improves the previous state of the art from 71.0% F1 to 75.9%...”，与缓存报告一致。
3. **导出到 Word**：应用提示“已导出 `manuscript（Clover）.docx`，保存在「guyingjie_mrc」文件夹，
   共 64 条批注、21 处修订”。WPS 打开后停在第 29/42 页，右侧批注栏显示
   `Jackie｜被引文献不支持这条论断｜依据：……`，正文中“F1 值提高 5.5%”带批注锚点。
   对导出件做结构核对：`word/comments.xml` 64 条批注，`word/document.xml` 21 个 `w:ins`、
   20 个 `w:del`（21 处修订），与提示数字一致；错别字确实是修订（tracked changes），不是直接改字。
   导出件只在 WPS 内存里查看，未保存任何改动（磁盘文件保持导出原样），且未提交（`demo/testset` 在忽略规则内）。
4. **插图**：报告阅读区的“图 9 BiDAF 的双向注意力机制”正常渲染（`gu-02` 中可见），导出后在 WPS 中也能显示。

## 4. 可选：现场重跑

**未执行。** 这台机器的 `demo/testset` 下没有任何被引 PDF（`*.pdf` 搜索结果为空），
而缓存报告是在 Mac 上带 72 篇本地原文跑的；在这里重跑缺少原文证据，结果与 r1105 不可比。
按清单“可选”处理，现场仍按原计划直接打开缓存报告，不重新体检。

## 5. 现场状态

- 应用用 `C:\clover-data\start_ready_app.cmd` 重新启动，停在首页；缓存库为
  `C:\clover-data\shots\ready.sqlite`，其中只有第 2 步那行报告，没有模型判断缓存。
- 任务管理器停在“性能 → GPU”，引擎下拉为 **Compute**；窗口带 `WS_EX_TOPMOST`，已浮在
  Clover 之上（置顶）。
- 网络与百炼 Key：用应用同一份 `c-home` 配置请求 `GET /models`，返回 **182 个模型**，Key 与网络正常。

## 截图

- `demo/intel/shots-pitch/win/gu-01-history.png` — 首页历史列表
- `demo/intel/shots-pitch/win/gu-02-f43.png` — f43 详情与正文高亮
- `demo/intel/shots-pitch/win/gu-03-wps.png` — WPS 中的批注
