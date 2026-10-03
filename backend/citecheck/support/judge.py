"""支持度判断 (task 'judge', cloud only per router policy).

Prompt contract (PLAN T3): claim + cited title + excerpt in; JSON
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
    "你是严谨的学术评审。判断“被引文献原文片段”是否支持“论断”。\n"
    "论断：{claim}\n"
    "{sentence_line}"
    "被引文献标题：{title}\n"
    "被引文献原文片段：{excerpt}\n\n"
    "输出 JSON：{{\"label\": \"supported|partial|unsupported|undetermined\", "
    "\"evidence\": \"...\", \"rationale\": \"...\", \"off_topic\": false}}。\n"
    "规则：evidence 必须从原文片段中原样摘抄，不超过两句；rationale 用一句"
    "中文说明判断依据；如果原文片段没有涉及该论断，label 用 undetermined，"
    "不要猜测。\n"
    "只判断论断中归属给这篇被引文献的内容。论断里属于作者本人的做法、实验设置、"
    "应用方式或观点（例如“我们把 X 用在 Y 上”“X 被用作基线”“但这并不能……”），"
    "不需要被引文献支持，不能因此判 partial。引用工具、数据集或方法时，只要文献"
    "确实提出或提供了它，就是 supported。措辞不同但意思一致不算 partial。partial "
    "只用于：归属给这篇文献的内容里，有实质的一部分文献并不支持。\n"
    "off_topic：只有当被引文献整体的研究对象（看标题和片段）与论断讨论的对象"
    "明显不是一回事时才填 true，例如论断讲 LoRA 的原理而文献是关于 DPO 的；"
    "如果文献主题相关、只是片段没提到这个细节，填 false。只输出 JSON。"
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
    correction: bool = False,
    task: str = "judge",
) -> JudgeOut | None:
    """One judging pass. ``task`` selects the configured model: 'judge'
    for the first pass, 'review'/'review_fallback' for the cascade."""
    prompt = _PROMPT.format(
        claim=claim_text,
        sentence_line=f"所在句子：{sentence}\n" if sentence else "",
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
