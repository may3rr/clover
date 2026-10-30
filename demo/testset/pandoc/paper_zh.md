---
title: "面向科技文献的引文核验方法研究"
author:
  - 陈明
  - 李华
---

# 引言

预训练语言模型改变了科技文本的处理方式[@vaswani2017attention; @devlin2019bert]。在中文领域，学者对引文分析开展了大量研究[@qiu2010citation]，引文内容分析被用于评价学术影响[@liu2019content]。

# 相关研究

## 引文功能识别

引文功能识别关注作者为何引用[@teufel2006automatic]。国内研究者构建了中文引文功能语料[@li2021function]，并比较了多种分类模型[@liu2019content; @li2021function]。

## 事实核验

SciFact 数据集用于核验科学论断[@wadden2020fact]。

# 方法

表 1 列出本文使用的模型。

| 模块 | 模型 |
|------|------|
| 检索 | DPR |
| 判断 | NLI 分类器 |

: 方法模块 {#tbl:modules}

# 结论

检索信号有助于引文核验[@wadden2020fact]。

# 参考文献 {-}

::: {#refs}
:::
