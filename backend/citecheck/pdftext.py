"""Text of one PDF page with pypdf, tolerant of producer quirks."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _resolve_widths(page) -> None:
    """Some producers (CNKI journal PDFs among them) store font width
    entries as indirect objects; pypdf then fails on adding a float to
    an IndirectObject. Resolve them in place before extracting text."""
    from pypdf.generic import ArrayObject, IndirectObject, NameObject

    def flat(arr) -> None:
        for i, x in enumerate(arr):
            if isinstance(x, IndirectObject):
                arr[i] = x = x.get_object()
            if isinstance(x, ArrayObject):
                flat(x)

    fonts = (page.get("/Resources") or {}).get("/Font") or {}
    for ref in fonts.get_object().values():
        font = ref.get_object()
        for d in [font] + [x.get_object() for x in font.get("/DescendantFonts") or []]:
            for key in ("/W", "/Widths"):
                if key in d:
                    w = d[key].get_object()
                    if isinstance(w, ArrayObject):
                        flat(w)
                        d[NameObject(key)] = w


def page_text(page) -> str:
    """One page's text; a page pypdf cannot read is empty rather than
    failing the whole file."""
    try:
        _resolve_widths(page)
    except Exception as e:  # noqa: BLE001 — extraction may still succeed
        log.debug("pdf: font widths left as they are: %s", e)
    try:
        return page.extract_text() or ""
    except Exception as e:  # noqa: BLE001
        log.debug("library: page text failed: %s", e)
        return ""
