"""Record real Qwen judge responses for the 10 support pairs.

Run once with DASHSCOPE_API_KEY configured:
    python tests/fixtures/record_llm.py
Writes tests/fixtures/llm/support_pairs.json "recorded" section.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from citecheck.support.judge import judge_claim

PATH = Path(__file__).parent / "llm" / "support_pairs.json"


async def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    for pair in data["pairs"]:
        out = await judge_claim(pair["claim"], pair["title"], pair["excerpt"])
        if out is None:
            print(f"{pair['id']}: model returned invalid output")
            continue
        data["recorded"][pair["id"]] = out.model_dump()
        print(f"{pair['id']}: {out.label}  (expected {pair['expected']})")
    PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
