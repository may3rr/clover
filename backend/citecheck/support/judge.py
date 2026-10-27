"""支持度判断 (task 'judge', cloud only per router policy).

Prompt contract (PLAN T3): claim + cited entry/title + excerpt in; JSON
{label, evidence, rationale} out. evidence must be copied verbatim from
the excerpt (<=2 sentences), rationale one Chinese sentence, and the
model must answer undetermined rather than guess.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..llm.client import chat_json


class JudgeOut(BaseModel):
    label: Literal["supported", "partial", "unsupported", "undetermined"]
    evidence: str | None = None
    rationale: str = ""
    # the cited work is about something else entirely (a likely miscitation),
    # as opposed to an excerpt that merely doesn't mention the detail
    off_topic: bool = False


_PROMPT = (
    "你是严谨的学术评审。判断“被引文献”是否支持“论断”。\n"
    "论断：{claim}\n"
    "{sentence_line}"
    "{entry_line}"
    "被引文献标题：{title}\n"
    "被引文献原文片段（文献开头与和论断最相关的段落）：{excerpt}\n\n"
    "输出 JSON：{{\"label\": \"supported|partial|unsupported|undetermined\", "
    "\"evidence\": \"...\", \"rationale\": \"...\", \"off_topic\": false}}。\n"
    "按顺序判断：\n"
    "0. 论断本身残缺、看不出在说什么（例如只剩一个词、半句话或表格标题）时，"
    "label 用 undetermined，不再往下判断。\n"
    "1. 先根据条目、标题和片段开头确认这篇文献是什么工作。论断把某个具名的方法、"
    "模型、数据集或某位作者的工作归属给这条引用，而这篇文献明显是另一项工作，"
    "例如论断说“Huang 等人提出的 FusionNet”，文献却是别的作者提出的别的模型，"
    "或者文献只是在相关工作里转述了那项工作；又或者文献整体的研究对象与论断讨论的"
    "对象不是一回事：off_topic 填 true，label 用 unsupported，evidence 摘抄片段中"
    "能说明文献实际内容的一句。\n"
    "2. 文献就是论断所说的工作时，逐项核对论断归属给它的具体内容：数值、比较方向、"
    "程度、对象、数据集或知识库名称、因果和先后关系。原文明确写的与论断不一致时，"
    "核心内容不一致用 unsupported，次要细节不一致用 partial，不能因为大意相近判 "
    "supported。片段里没写到的内容不算不一致；约数、四舍五入和换算后的数值算一致。\n"
    "3. 文献主题一致、但片段没有涉及论断的具体内容时，label 用 undetermined，"
    "不要猜测。\n"
    "规则：evidence 必须是片段中一段连续的原文，原样摘抄，不超过两句，不要用省略号"
    "拼接不相邻的句子，保持原文的语言，论断是中文而原文是英文时也不要翻译；"
    "rationale 用一句中文说明判断依据。\n"
    "所在句子同时引了多篇文献时，这篇文献只需支持句中与它相关的那一部分，例如"
    "句中提到的某个方法、模型或数据集正是它提出的；其余部分由别的文献负责，不能"
    "因此判 partial 或 unsupported。句中没有任何部分与它相关时才按第 1 步处理。\n"
    "只判断论断中归属给这篇被引文献的内容。论断里属于作者本人的做法、实验设置、"
    "应用方式或观点（例如“我们把 X 用在 Y 上”“X 被用作基线”“但这并不能……”），"
    "不需要被引文献支持，不能因此判 partial。引用工具、数据集或方法时，只要文献"
    "确实提出或提供了它，就是 supported。措辞不同但意思一致不算 partial。"
    "如果文献主题相关、只是片段没提到这个细节，off_topic 填 false。只输出 JSON。"
)

_CORRECTION = (
    "\n\n注意：你上一次给出的 evidence 未能在原文片段中逐字定位。这次必须把"
    " evidence 写成片段中一段完全连续的原文文字；如果片段里确实没有可作为"
    "证据的文字，label 用 undetermined，evidence 留空。"
)


async def judge_claim(
    claim_text: str,
    ref_title: str | None,
    excerpt: str,
    *,
    sentence: str | None = None,
    entry: str | None = None,
    correction: bool = False,
    task: str = "judge",
) -> JudgeOut | None:
    """One judging pass. ``task`` selects the configured model: 'judge'
    for the first pass, 'review'/'review_fallback' for the cascade."""
    prompt = _PROMPT.format(
        claim=claim_text,
        sentence_line=f"所在句子：{sentence}\n" if sentence else "",
        entry_line=f"被引文献条目（稿件参考文献表中的著录）：{entry}\n" if entry else "",
        title=ref_title or "（无标题）",
        excerpt=excerpt,
    )
    if correction:
        prompt += _CORRECTION
    res = await chat_json(
        task,
        [{"role": "user", "content": prompt}],
        JudgeOut,
    )
    return res.value
