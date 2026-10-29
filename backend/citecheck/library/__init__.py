"""文献文件夹（reference library）：扫描、连接、作为本地证据来源。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from ..schema import Library, LibraryLink, Reference
from .link import assemble, link_library
from .scan import LocalPdf, scan_folder, unsupported_files
from .venue_match import annotate_venues


async def build_library(
    refs: list[Reference], folder: str | Path, *,
    links: list[LibraryLink] | None = None, venue: str | None = None,
    use_model: bool = True, cache=None, progress=None,
    pdfs: list[LocalPdf] | None = None,
    exemplar_ids: list[str] | None = None, fallback_venue: str | None = None,
    manuscript_type: str = "research", guess_venues: bool | None = None,
    on_stage: Callable[[str, int, int], None] | None = None,
) -> tuple[Library, dict[str, LocalPdf], list[LocalPdf]]:
    """Scan ``folder`` and link it to ``refs``. ``links`` given = the
    user's confirmed table from the confirmation step: kept as they are
    (dangling ids dropped, one PDF per entry), marked confirmed; likewise
    ``exemplar_ids``, the user's exemplar selection. Returns the report
    record, ref_id -> LocalPdf for the layers, and every scanned PDF
    (exemplars are read from it). ``on_stage(stage, done, total)`` reports
    "pdfs", "link", "ask" and "venue" for the scan screen."""
    note = on_stage or (lambda _s, _d, _t: None)
    if guess_venues is None:
        from ..config import venue_model_enabled

        guess_venues = venue_model_enabled()
    opts = dict(exemplar_ids=exemplar_ids, fallback_venue=fallback_venue,
                manuscript_type=manuscript_type)
    if pdfs is None:
        def _pdf_progress(done: int, total: int) -> None:
            note("pdfs", done, total)
            if progress is not None:
                progress(done, total)

        pdfs = await asyncio.to_thread(scan_folder, folder, cache, _pdf_progress)
    if links is None:
        lib = await link_library(refs, pdfs, str(folder), use_model=use_model, venue=venue,
                                 guess_venues=guess_venues, on_stage=on_stage, **opts)
    else:
        ref_ids = {r.id for r in refs}
        doc_ids = {p.doc.id for p in pdfs}
        kept: list[LibraryLink] = []
        seen_refs: set[str] = set()
        seen_docs: set[str] = set()
        for x in links:
            if (x.ref_id in ref_ids and x.doc_id in doc_ids
                    and x.ref_id not in seen_refs and x.doc_id not in seen_docs):
                kept.append(x.model_copy(update={"status": "confirmed"}))
                seen_refs.add(x.ref_id)
                seen_docs.add(x.doc_id)
        await annotate_venues(pdfs, seen_docs, use_model=use_model and guess_venues)
        lib = assemble(kept, pdfs, str(folder), venue, **opts)
    lib.unsupported = unsupported_files(folder)
    by_doc = {p.doc.id: p for p in pdfs}
    local = {x.ref_id: by_doc[x.doc_id] for x in lib.links}
    return lib, local, pdfs


__all__ = ["build_library", "LocalPdf", "scan_folder"]
