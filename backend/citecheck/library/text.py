"""Text clean-up for locally extracted PDF text, zh and en alike.

pypdf puts a space between almost every glyph of a typeset Chinese PDF
("代 伟", "0 . 259", "［ J ］") and hard-wraps every line. Everything that
reads PDF text (library scan, BM25 windows, evidence matching) goes
through the same rules so offsets and verbatim checks agree.
"""

from __future__ import annotations

import re
import unicodedata

# CJK ideographs, CJK punctuation, fullwidth forms
_CJK = r"　-〿㐀-䶿一-鿿＀-￯"
_CJK_CHAR_RE = re.compile(f"[{_CJK}]")
# whitespace with a CJK char on at least one side carries no meaning
_CJK_SPACE_RE = re.compile(f"(?<=[{_CJK}])[ \\t]+|[ \\t]+(?=[{_CJK}])")
# "0 . 259" / "10 . 11925" — spaced decimal points and DOI dots
_SPACED_DOT_RE = re.compile(r"(?<=\d) \. (?=\d)")


_FULLWIDTH_RE = re.compile("[０-９Ａ-Ｚａ-ｚ［］／＿－＋＝＠＃＆　]")


def is_cjk(ch: str) -> bool:
    return bool(_CJK_CHAR_RE.match(ch))


def squash_cjk_spaces(text: str) -> str:
    text = _CJK_SPACE_RE.sub("", text)
    return _SPACED_DOT_RE.sub(".", text)


def clean_page(text: str) -> str:
    """One page of pypdf output -> readable running text."""
    # fullwidth ＡＢＣ / ［Ｊ］ / １２ in older typesetting -> ASCII; Chinese
    # punctuation （，。：） stays as the author wrote it
    text = _FULLWIDTH_RE.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)),
                             text).replace("\N{SOFT HYPHEN}", "")
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)  # de-hyphenate
    lines = [ln.strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln:
            continue
        if out and (is_cjk(out[-1][-1]) or is_cjk(ln[0])):
            out[-1] += ln  # Chinese lines join without a space
        elif out:
            out[-1] += " " + ln
        else:
            out.append(ln)
    return re.sub(r"[ \t]{2,}", " ", squash_cjk_spaces("".join(out))).strip()


def squash(text: str) -> str:
    """Comparison key: lowercase letters, digits and CJK ideographs only."""
    return re.sub(r"[^0-9a-z一-鿿]+", "", (text or "").lower())
