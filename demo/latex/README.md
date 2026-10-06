# LaTeX 样例集

四篇 arXiv 知名论文的 LaTeX 源码，每篇故意注入 6 至 7 处错误，用来检验 LaTeX 导入和四层体检的检出能力。四篇覆盖了三种常见的参考文献组织方式。

| 样例 | 论文 | 参考文献组织 | 引用样式 | 注入 |
| --- | --- | --- | --- | --- |
| `attention.zip` | Attention Is All You Need（1706.03762） | 正文内嵌 `thebibliography` | 数字编号 | 7 |
| `bert.zip` | BERT（1810.04805） | 只有编译产物 `main.bbl`，没有 `.bib` | natbib 作者-年份，ACL `\newcite` | 7 |
| `lora.zip` | LoRA（2106.09685） | 两个 `.bib`，去掉 `.bbl`（模拟 Overleaf 下载） | natbib 作者-年份 | 6 |
| `qlora.zip` | QLoRA（2305.14314） | `references.bib`，去掉 `.bbl` | natbib 数字编号 | 7 |

注入类型与 Word 演示论文一致：编造文献（`fake_ref`）、年份错误（`wrong_year`）、首作者错误（`wrong_author`）、张冠李戴（`misattribution`，把引用换成内容无关的另一篇真实文献）、错别字（`typo`）、未定义的引用键（`undefined_key`，编译后显示为 `[?]`）。每处注入的原文、改动和检出规则写在 `injections.json`。

LoRA 原文自带两处真实拼写错误（instrisic、comtenporary），评测会单独报告是否检出，不计入注入检出率。

## 用法

```bash
source /opt/anaconda3/etc/profile.d/conda.sh && conda activate claude

# 重新生成样例包（arXiv 原始包缓存在 raw/，不进 git）
python demo/latex/build_samples.py

# 真实调用 Qwen 与检索 API 跑完整管线并打分；--reuse 复用 reports/ 的报告
python demo/latex/evaluate_latex.py
```

检出规则与 Word 演示论文的 `demo/evaluate.py` 一致，不放宽：张冠李戴必须被判为不支持并给出高严重度问题，只提示「可能引错了文献」的情况单独列出，不计入检出率。

评测输出每处注入是否检出、原文错别字是否检出、没有对应注入的高严重度问题（原论文本身也可能有真实问题，需要人工判断），并检查批注版导出是否成功、`clover-revisions.patch` 能否 `git apply` 到导出的项目上。结果写入 `eval_result.json`。

样例包只用于检验，不保证能直接编译：大于 500KB 的图片文件没有打进包里。在应用里直接拖入任一 zip 即可体检。
