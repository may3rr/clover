# 11 月 7 日下午：决赛机最终检查，载入顾迎捷论文的缓存报告

> 给 Intel 决赛机上的 agent。仓库在 `C:\clover`。按顺序做，结果写进 `demo/intel/FINAL_CHECK.md`，最后提交并 `git push cn intel`。遇到冲突或失败就停下来告诉用户，不要自己选一边。

## 1. 确认是最新代码

```powershell
cd C:\clover
git fetch cn
git merge cn/master
git merge-base --is-ancestor 5c071073 HEAD; if ($?) { "OK: 包含 Mac 最新提交" } else { "旧代码" }
git log -1 --format="%h %ad %s"
```

`5c071073` 是 Mac 在 11-07 下午推送的提交，带来 `backend/scripts/import_report.py` 和 `demo/final/cached/guyingjie_mrc_r1105.json`。判断结果为「旧代码」时，不要继续往下做。

合并后在 `backend` 跑 pytest，在 `app` 下跑 `npm run typecheck`，把通过和跳过的数量写进 FINAL_CHECK.md。

## 2. 把顾迎捷论文的报告载入应用的历史列表

这份报告是 11 月 5 日在 Mac 上跑的 r1105。在这一轮里，[100] Xiong 等 DCN 那条论断（HMN 让 F1 提高 5.5%）判为「被引文献不支持这条论断」，也就是路演 PPT 第 3 页的例子。这条判断在不同运行之间并不稳定：r1104 判为部分支持，r1104b 判为支持。所以现场要展示这一条时，直接打开这份报告，不要重新体检。

先确认应用平时用的是哪一个缓存库：看现场启动应用时 `CITECHECK_HOME`、`CITECHECK_CACHE` 的值，以及 `config.toml` 里 `[cache] path` 的值。根据 `demo/intel/shots-pitch/README.md`，应该是 `C:\clover-data\shots\ready.sqlite`。然后导入：

```powershell
cd C:\clover\backend
$env:CITECHECK_CACHE = "<上面确认的缓存库路径>"
uv run python scripts\import_report.py ..\demo\final\cached\guyingjie_mrc_r1105.json ..\demo\testset\zh_papers\guyingjie_mrc\manuscript.docx
```

正常输出：`imported-d02a7ec2023720bca  基于神经网络的机器阅读理解综述  findings 64 {'high': 33, 'medium': 10, 'low': 21}`。

如果报 `is not the file this report was made from`，说明 docx 的换行或内容被改动过。这时用 `git checkout -- demo/testset/zh_papers/guyingjie_mrc/manuscript.docx` 恢复后再导入。

导入只往 reports 表里写一行，不写模型判断的缓存。评委现场拖入新稿件时，仍然会真正调用模型。

## 3. 在应用里核对

用现场的配置启动应用，在首页的历史列表里打开「基于神经网络的机器阅读理解综述」，逐项核对并截图，截图存到 `demo/intel/shots-pitch/win/gu-*.png`：

1. 历史列表里能看到这篇论文：`gu-01-history.png`。
2. 打开报告，在检查器里找到 `f43`「被引文献不支持这条论断」，正文高亮落在「……HMN 模块可以使模型在 SQuAD1.1 数据集上的 F1 值提高 5.5%」这一段，详情里有 [100] 的原文证据：`gu-02-f43.png`。
3. 点「导出到 Word」，生成的 `manuscript（Clover）.docx` 用 WPS 打开，确认这一条是批注，错别字是修订：`gu-03-wps.png`。导出的 docx 不要提交。
4. 插图能正常显示。如果显示不出来，记下来，这一项不阻塞。

## 4. 可选：现场重跑这篇，看判断是否一致

只有时间够、网络正常的时候才做。另开一个数据目录，不要碰现场那份空缓存：

```powershell
$env:CITECHECK_HOME = "C:\clover-data\gu-rerun"
$env:CITECHECK_CACHE = "C:\clover-data\gu-rerun\cache.sqlite"
```

用推荐配置拖入 `demo\testset\zh_papers\guyingjie_mrc\manuscript.docx` 体检一次。记录用时、问题总数，以及 [100] 那条论断的判定是支持、部分支持、不支持还是无法判断。重跑结果和 r1105 不一致也照实记录，不要改配置去凑结果。

## 5. 恢复现场状态

- 应用用现场配置重新启动，停在首页，缓存库是第 2 步那个，里面没有模型判断的缓存。
- 任务管理器停在「性能 → GPU」，引擎下拉选 Compute，并设为置于顶层。
- 确认网络和百炼 API Key 可用：在设置页点获取模型列表能返回结果即可。

## 6. 汇报

`demo/intel/FINAL_CHECK.md` 里写清这几项：

- 合并后的 HEAD；是否包含 `5c071073`；pytest 和 typecheck 的结果。
- 导入命令的输出。
- 第 3 步四项核对的结果。
- 如果做了第 4 步，写上重跑的结果。
- 现场状态是否已经恢复。

然后执行：

```powershell
git add demo/intel/FINAL_CHECK.md demo/intel/shots-pitch/win/gu-*.png
git commit -m "Intel: final check, Gu MRC report imported into history"
git push cn intel
```
