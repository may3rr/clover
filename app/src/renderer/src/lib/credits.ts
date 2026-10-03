/** Everything the app is built on or learned from — shown in Settings ›
 * About and rolled in the credits easter egg. Only sources the project
 * actually uses, or that AGENTS.md names as design references. */

/** repo link shown in onboarding and About — update once the repo is public */
export const GITHUB_URL = 'https://github.com/may3rr/citecheck'

export type Credit = [name: string, role: string, url: string]

export const CREDITS: { group: string; items: Credit[] }[] = [
  {
    group: '设计参考',
    items: [
      ['Notion', '阅读区的排版、配色与属性行', 'https://www.notion.so'],
      ['macOS', '窗口、侧栏与设置界面的结构', 'https://developer.apple.com/design/human-interface-guidelines/'],
      ['GitHub', '账户页的活动热力图', 'https://github.com'],
    ],
  },
  {
    group: '文献数据',
    items: [
      ['Crossref', 'DOI 与出版元数据', 'https://www.crossref.org'],
      ['OpenAlex', '开放的学术图谱', 'https://openalex.org'],
      ['Semantic Scholar', '论文摘要与开放全文', 'https://www.semanticscholar.org'],
      ['arXiv', '预印本与领域对标语料', 'https://arxiv.org'],
    ],
  },
  {
    group: '开源软件',
    items: [
      ['Electron', '桌面应用外壳', 'https://www.electronjs.org'],
      ['React', '界面', 'https://react.dev'],
      ['Vite 与 electron-vite', '构建与开发服务', 'https://electron-vite.org'],
      ['Tailwind CSS', '布局工具类', 'https://tailwindcss.com'],
      ['TypeScript', '前端类型', 'https://www.typescriptlang.org'],
      ['FastAPI 与 Uvicorn', '本地后端服务', 'https://fastapi.tiangolo.com'],
      ['Pydantic', '数据模型与结构化输出校验', 'https://docs.pydantic.dev'],
      ['lxml 与 python-docx', '读取与写入 Word 文档', 'https://lxml.de'],
      ['HTTPX', '文献检索请求', 'https://www.python-httpx.org'],
      ['RapidFuzz', '标题与作者的模糊匹配', 'https://github.com/rapidfuzz/RapidFuzz'],
      ['rank-bm25', '证据片段检索', 'https://github.com/dorianbrown/rank_bm25'],
      ['pypdf', '读取开放全文', 'https://github.com/py-pdf/pypdf'],
      ['OpenAI Python SDK', '调用 OpenAI 兼容接口', 'https://github.com/openai/openai-python'],
      ['LobeHub Icons', '服务商图标（MIT）', 'https://github.com/lobehub/lobe-icons'],
    ],
  },
  {
    group: '片尾配乐',
    items: [
      ['Claude Debussy', '《月光》，8-bit 改编', 'https://imslp.org/wiki/Suite_bergamasque_(Debussy%2C_Claude)'],
      ['Mutopia Project', '公有领域乐谱与 MIDI', 'https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=1778'],
    ],
  },
]
