<p align="center">
  <img src="app/build/icon.svg" width="128" height="128" alt="Clover">
</p>

<h1 align="center">Clover</h1>

<p align="center"><b>The last mile of the paper.</b> 投稿的最后一公里</p>

<p align="center">
  <a href="https://jackielyu.is-a.dev/clover/">主页与在线界面</a> ·
  <a href="https://github.com/may3rr/clover/releases/latest/download/Clover-mac-arm64.dmg">下载 macOS 版</a> ·
  <a href="https://github.com/may3rr/clover/releases">版本发布</a>
</p>

Clover 是一个 macOS 桌面应用。拖入一篇 `.docx` 论文，它会核对参考文献是否真实存在，检查正文中每一处论断是否得到被引文献支持，把引用分布放回领域常态中比较，并找出格式问题。检查结果可以一键导出成新的 Word 文件：实质性问题写成批注，错别字等机械性问题写成修订，由作者在 Word 里逐条处理。

> **天猫 AI 黑客松参赛项目。** 参赛队伍：我要发顶刊。赛道：效率进化，阿里云特别赛题（基于 Qwen 的科研提效）。
> [比赛页面](https://pages.tmall.com/wow/a/act/tmall/dailygroup/24732/25590/wupr)

## 为什么做 Clover

大语言模型和多智能体工具普及以后，研究者从一个想法走到一组实验结果的时间缩短了很多，投稿量也随之增长。一篇论文投出之前，作者仍要为学术诚信做大量手工核对：参考文献是否真实存在，作者、年份和 DOI 是否无误，每一处引用是否确实支持对应的论断。这些核对繁琐耗时，也最容易在截稿前被压缩。Clover 尝试把这份核对自动化：核对交给机器，判断留给作者。

## 四层检查

| 层 | 做什么 |
| --- | --- |
| 文献真实性 | 每条参考文献到 Crossref、OpenAlex、Semantic Scholar 和 arXiv 核对，指出作者、年份、DOI 的不一致；几个库都真正应答且都没有记录，才判定为找不到 |
| 论断支持度 | 抽出正文中的论断与引用，到被引文献的摘要和开放全文里找证据；证据必须能在原文中逐字找到，否则降级为无法判断 |
| 引用分布 | 对照 150 篇 arXiv 计算语言学论文，逐章比较引用密度与引用功能，单独指出引用堆砌 |
| 格式规范 | 错别字、未被引用的文献、找不到条目的引用、文献重新排序 |

可选的期刊评审：选定 EMNLP、ACL 或 NAACL，对照该会议已发表的相近论文，从实验规模、分析深度、文献覆盖、引用可靠性和结构完整五个方面给出定位。

## 原则

- **只给机械性问题写修订。** 错别字、文献重排与随之变化的引用编号写成修订；编造或不符的文献、张冠李戴的引用、缺少支撑的论断只写批注。Clover 不改写正文，不删除或替换参考文献，也不推荐该引哪篇。
- **证据可追溯。** 每个支持或不支持的判断都附被引文献的原文片段。
- **不确定就说不确定。** 查不到的标为无法核验，不会说成不存在。
- **稿件留在本机。** 全文在本机解析，云端只接收需要复核的论断和证据片段。原文件永不覆盖。

## 安装

1. 下载 [Clover-mac-arm64.dmg](https://github.com/may3rr/clover/releases/latest/download/Clover-mac-arm64.dmg)，拖进“应用程序”。适用于 Apple 芯片的 Mac。
2. 应用尚未经过 Apple 公证。第一次打开如果被拦下，到 **系统设置 › 隐私与安全性** 点 **仍要打开**，或在终端运行一次 `xattr -cr /Applications/Clover.app`。
3. 在首次启动的引导或 **设置 › 模型** 中填入阿里云百炼（DashScope）API Key。Key 只保存在 `~/Library/Application Support/Clover/.env`。

目前只支持英文论文。英文期刊和会议的元数据、摘要与开放全文更容易获取，中文文献的核验与对标会在之后补上。

## 模型

全程使用通义千问 Qwen 系列，经阿里云百炼的 OpenAI 兼容接口调用，模型名全部写在 `backend/config.toml`：

| 任务 | 默认模型 |
| --- | --- |
| 支持度判断、错别字 | qwen3.8-flash |
| 复核存疑结论 | qwen3.8-max |
| 文献结构化、论断抽取、引用功能 | qwen3.7-flash |
| 本地论断抽取（可选） | MLX 运行的 Qwen2.5-3B-Instruct 4bit，失败自动回退云端 |

判断类调用温度为 0，输出结构化 JSON 并经 Pydantic 校验。所有调用都有缓存和用量记录，实测一次完整检查约 0.19 元。

## 从源码运行

```bash
# 后端（Python 3.11+）
cd backend
cp .env.example .env                 # 填入 DASHSCOPE_API_KEY
cp config.example.toml config.toml
pip install -e ".[dev]"
python -m pytest -q

# 桌面应用（Node 22）
cd ../app
npm install
CITECHECK_PYTHON=$(which python) npm run dev
```

打包：`npm run dist`。脚本会把独立的 CPython 和后端依赖打进 `Clover.app`，再生成 `release/Clover-mac-arm64.dmg`。推送 `v*` 标签后，GitHub Actions 会在 Apple 芯片的 runner 上构建，并把安装包上传到 Release。

## 目录

```
backend/      FastAPI 本地服务：解析、四层检查、Word 导出（citecheck 是工作代号）
app/          Electron + React 桌面应用
app/site/     产品主页：在网页里原样运行应用界面，部署到 GitHub Pages
demo/         演示论文与生成脚本
```

主页里的界面就是应用本身的渲染代码，后端由浏览器内的模拟替代，数据来自对演示论文的真实运行。`npm run site:dev` 本地预览，`npm run site:record` 把预设的操作脚本录成视频。

## 致谢

Clover 建立在这些开源项目、开放数据和设计参考之上。

**文献数据**：[Crossref](https://www.crossref.org)、[OpenAlex](https://openalex.org)、[Semantic Scholar](https://www.semanticscholar.org)、[arXiv](https://arxiv.org)（也是领域对标语料的来源）、[ACL Anthology](https://aclanthology.org)（期刊评审的参照论文）。

**模型与平台**：[通义千问 Qwen](https://github.com/QwenLM)、[阿里云百炼](https://bailian.console.aliyun.com)、[MLX](https://github.com/ml-explore/mlx) 与 [mlx-lm](https://github.com/ml-explore/mlx-lm)。

**开源软件**

| 项目 | 用途 |
| --- | --- |
| [Electron](https://www.electronjs.org)、[electron-vite](https://electron-vite.org)、[electron-builder](https://www.electron.build) | 桌面应用外壳、构建与打包 |
| [React](https://react.dev)、[TypeScript](https://www.typescriptlang.org)、[Vite](https://vite.dev)、[Tailwind CSS](https://tailwindcss.com) | 界面 |
| [FastAPI](https://fastapi.tiangolo.com)、[Uvicorn](https://www.uvicorn.org)、[sse-starlette](https://github.com/sysid/sse-starlette)、[python-multipart](https://github.com/Kludex/python-multipart) | 本地后端服务 |
| [Pydantic](https://docs.pydantic.dev) | 数据模型与结构化输出校验 |
| [lxml](https://lxml.de)、[python-docx](https://github.com/python-openxml/python-docx) | 读取与写入 Word 文档 |
| [HTTPX](https://www.python-httpx.org) | 文献检索请求 |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | 标题与作者的模糊匹配 |
| [rank-bm25](https://github.com/dorianbrown/rank_bm25) | 证据片段检索 |
| [pypdf](https://github.com/py-pdf/pypdf) | 读取开放全文 |
| [pypinyin](https://github.com/mozillazg/python-pinyin) | 中文作者名处理 |
| [OpenAI Python SDK](https://github.com/openai/openai-python) | 调用 OpenAI 兼容接口 |
| [uv](https://github.com/astral-sh/uv)、[python-build-standalone](https://github.com/astral-sh/python-build-standalone) | 打进应用的独立 Python 运行时 |
| [LobeHub Icons](https://github.com/lobehub/lobe-icons) | 设置页的服务商图标 |
| [pytest](https://pytest.org)、[Vitest](https://vitest.dev) | 测试 |

**设计参考**：[Notion](https://www.notion.so) 的阅读区排版与配色，[macOS](https://developer.apple.com/design/human-interface-guidelines/) 的窗口、侧栏与设置界面，GitHub 的活动热力图。

**片尾彩蛋**：[Mutopia Project](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=1778) 提供德彪西《月光》的公有领域乐谱。

**特别感谢**

- [Qwen3.8-Max](https://qwen.ai)：复核每一条存疑的结论，是 Clover 判断可靠的最后一道关。
- [Qoder](https://qoder.com)：千问的编程智能体，和我们一起写了这个应用。
- [Claude Code](https://www.anthropic.com/claude-code)（Claude Opus 5.5）：同样参与了编程。

## 许可证

[PolyForm Noncommercial 1.0.0](LICENSE.md)。个人、学生、科研与教学等非商业用途可以免费使用、修改和分发；商业用途需要另行取得授权，请联系作者。
