"""文献文件夹（reference library）：扫描、连接、作为本地证据来源。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..schema import Library, LibraryLink, Reference
from .link import assemble, link_library
from .scan import LocalPdf, scan_folder, unsupported_files


async def build_library(
    refs: list[Reference], folder: str | Path, *,
    links: list[LibraryLink] | None = None, venue: str | None = None,
    use_model: bool = True, cache=None, progress=None,
    pdfs: list[LocalPdf] | None = None,
) -> tuple[Library, dict[str, LocalPdf], list[LocalPdf]]:
    """Scan ``folder`` and link it to ``refs``. ``links`` given = the
    user's confirmed table from the confirmation step: kept as they are
    (dangling ids dropped, one PDF per entry), marked confirmed.
    Returns the report record, ref_id -> LocalPdf for the layers, and
    every scanned PDF (exemplars are read from it)."""
    if pdfs is None:
        pdfs = await asyncio.to_thread(scan_folder, folder, cache, progress)
    if links is None:
        lib = await link_library(refs, pdfs, str(folder), use_model=use_model, venue=venue)
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
        lib = assemble(kept, pdfs, str(folder), venue)
    lib.unsupported = unsupported_files(folder)
    by_doc = {p.doc.id: p for p in pdfs}
    local = {x.ref_id: by_doc[x.doc_id] for x in lib.links}
    return lib, local, pdfs


__all__ = ["build_library", "LocalPdf", "scan_folder"]
