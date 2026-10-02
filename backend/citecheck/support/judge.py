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


_PROMPT = (
    "你是严谨的学术评审。判断“被引文献原文片段”是否支持“论断”。\n"
    "论断：{claim}\n"
    "被引文献标题：{title}\n"
    "被引文献原文片段：{excerpt}\n\n"
    "输出 JSON：{{\"label\": \"supported|partial|unsupported|undetermined\", "
    "\"evidence\": \"...\", \"rationale\": \"...\"}}。\n"
    "规则：evidence 必须从原文片段中原样摘抄，不超过两句；rationale 用一句"
    "中文说明判断依据；如果原文片段没有涉及该论断，label 用 undetermined，"
    "不要猜测。只输出 JSON。"
)


async def judge_claim(
    claim_text: str, ref_title: str | None, excerpt: str
) -> JudgeOut | None:
    res = await chat_json(
        "judge",
        [
            {
                "role": "user",
                "content": _PROMPT.format(
                    claim=claim_text,
                    title=ref_title or "（无标题）",
                    excerpt=excerpt,
                ),
            }
        ],
        JudgeOut,
    )
    return res.value
