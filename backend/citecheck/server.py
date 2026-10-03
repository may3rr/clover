"""本地 FastAPI 服务（127.0.0.1:8765），供 Electron 前端调用。

- POST /analyze：multipart `file` 或表单字段 `path`（本地路径，原地读取，
  不修改），可选 `benchmark`；返回 {job_id}。
- GET /jobs/{id}/events：SSE，先回放已有事件再推送新事件，done/failed
  后关闭。
- GET /jobs/{id}/report：运行中返回 409。
- GET /benchmarks：backend/benchmarks/*.json 的 [{id, name, n_papers}]。
- POST /jobs/{id}/export：{path}。
- GET /reports：历史报告列表（体检完成即落库，id = job_id）；
  GET /reports/{id} 取完整报告，DELETE 删除，POST /reports/{id}/export
  用库存报告与原始 docx 导出（原文件缺失返回 400）。

鉴权：环境变量 CITECHECK_TOKEN 存在时，除 /health 外所有路由要求
X-Citecheck-Token 头或 ?token= 查询参数（EventSource 无法设置请求头）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from .cache import Cache
from .config import get_settings
from .pipeline import PipelineError, run_pipeline

log = logging.getLogger(__name__)

TOKEN = os.environ.get("CITECHECK_TOKEN")
BENCH_DIR = Path(__file__).resolve().parents[1] / "benchmarks"
_UPLOADS = Path(tempfile.gettempdir()) / "citecheck_uploads"

app = FastAPI(title="citecheck")
# 本地服务；token 存在时仍要求鉴权，'*' 只在没有 token 的开发模式下裸奔
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _auth(request: Request, call_next):
    # OPTIONS is the CORS preflight — it carries no credentials; the real
    # request behind it is still checked.
    if TOKEN and request.method != "OPTIONS" \
            and request.url.path != "/health":
        given = request.headers.get("x-citecheck-token") or \
            request.query_params.get("token")
        if not (given and secrets.compare_digest(given, TOKEN)):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


@dataclass
class Job:
    id: str
    src_path: Path
    events: list[dict] = field(default_factory=list)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    report: object | None = None
    error: str | None = None
    task: asyncio.Task | None = None


JOBS: dict[str, Job] = {}

PREFS_KEY = "prefs"
_DEFAULT_PREFS = {
    "name": "",
    # avatar: {"kind": "color"|"image", "color": "--tile-blue" etc,
    #          "image": data-url}
    "avatar": {"kind": "color", "color": "blue", "image": None},
    "comment_author": "",   # falls back to name, then Clover
    "comment_initials": "",  # falls back to derived
    "onboarded": False,      # first-run guide + privacy consent done
}


def _prefs() -> dict:
    p = Cache(get_settings().cache_path).get(PREFS_KEY)
    if not isinstance(p, dict):
        return dict(_DEFAULT_PREFS)
    merged = dict(_DEFAULT_PREFS)
    merged.update({k: v for k, v in p.items() if k in _DEFAULT_PREFS})
    if not isinstance(merged.get("avatar"), dict):
        merged["avatar"] = dict(_DEFAULT_PREFS["avatar"])
    return merged


def _comment_identity(p: dict) -> tuple[str, str]:
    """(author, initials) for exported docx comments."""
    author = (p.get("comment_author") or p.get("name") or "").strip()
    if not author:
        author = "Clover"
    initials = (p.get("comment_initials") or "").strip()
    if not initials:
        if len(author) <= 4:
            initials = author
        else:
            words = author.split()
            initials = (author[:2] if len(words) == 1 else
                        "".join(w[0] for w in words[:2])).upper()
    return author, initials


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/benchmarks")
async def benchmarks() -> list[dict]:
    out = []
    for p in sorted(BENCH_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": data.get("id", p.stem),
                        "name": data.get("name", p.stem),
                        "n_papers": data.get("n_papers", 0)})
        except (json.JSONDecodeError, OSError):
            continue
    return out


@app.post("/analyze")
async def analyze(
    request: Request,
    file: UploadFile | None = File(None),
    path: str | None = Form(None),
    benchmark: str = Form("arxiv_cs_cl"),
):
    if file is not None and file.filename:
        _UPLOADS.mkdir(parents=True, exist_ok=True)
        dest = _UPLOADS / f"{secrets.token_hex(8)}_{Path(file.filename).name}"
        with dest.open("wb") as fh:
            while chunk := await file.read(1 << 20):
                fh.write(chunk)
        src = dest
    elif path:
        src = Path(path)
        if not src.is_file():
            return JSONResponse({"detail": "文件不存在"}, status_code=400)
    else:
        return JSONResponse(
            {"detail": "需要 file 或 path"}, status_code=400)

    job = Job(id=secrets.token_hex(8), src_path=src)
    JOBS[job.id] = job

    def emit(ev: dict) -> None:
        job.events.append(ev)
        job.queue.put_nowait(ev)

    async def _run() -> None:
        try:
            job.report = await run_pipeline(
                src, benchmark_id=benchmark, emit=emit)
            _save_report(job.id, src, benchmark, job.report)
        except PipelineError as e:
            job.error = str(e)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job.id)
            job.error = str(e)
            emit({"type": "failed", "error": "体检过程中出现内部错误。"})

    job.task = asyncio.create_task(_run())
    return {"job_id": job.id}


def _save_report(report_id: str, src: Path, benchmark: str, rep) -> None:
    """Persist the finished report (id = job id) so /reports can list and
    reopen it later; export then works for live jobs and history alike."""
    try:
        counts = {"high": 0, "medium": 0, "low": 0}
        for f in rep.findings:
            if f.severity in counts:
                counts[f.severity] += 1
        Cache(get_settings().cache_path).save_report(
            report_id,
            rep.document.filename or src.name,
            (rep.document.title or "").strip() or src.stem,
            str(src),
            benchmark,
            counts,
            json.dumps(rep.model_dump(mode="json"), ensure_ascii=False),
        )
    except Exception:  # noqa: BLE001
        log.exception("failed to persist report %s", report_id)


# ---------------------------------------------------------------- reports


@app.get("/reports")
async def list_reports() -> list[dict]:
    return Cache(get_settings().cache_path).list_reports()


def _stored_report(report_id: str) -> dict | JSONResponse:
    row = Cache(get_settings().cache_path).get_report(report_id)
    if row is None:
        return JSONResponse({"detail": "report not found"}, status_code=404)
    return row


@app.get("/reports/{report_id}")
async def get_stored_report(report_id: str):
    row = _stored_report(report_id)
    if isinstance(row, JSONResponse):
        return row
    return JSONResponse(json.loads(row["report_json"]))


@app.delete("/reports/{report_id}")
async def delete_stored_report(report_id: str):
    if not Cache(get_settings().cache_path).delete_report(report_id):
        return JSONResponse({"detail": "report not found"}, status_code=404)
    return {"ok": True}


@app.post("/reports/{report_id}/export")
async def export_stored_report(report_id: str):
    row = _stored_report(report_id)
    if isinstance(row, JSONResponse):
        return row
    src = Path(row["src_path"])
    if not src.is_file():
        return JSONResponse(
            {"detail": "原文件已移动或删除，无法导出。请重新体检这篇论文。"},
            status_code=400,
        )
    try:
        from .export import export_report
        from .schema import Report
        rep = Report.model_validate(json.loads(row["report_json"]))
        author, initials = _comment_identity(_prefs())
        out = await asyncio.to_thread(
            export_report, src, rep, None, author, initials)
    except Exception as e:  # noqa: BLE001
        log.exception("export failed for stored report %s", report_id)
        return JSONResponse({"detail": str(e)}, status_code=500)
    return {"path": str(out)}


def _job(job_id: str) -> Job | JSONResponse:
    job = JOBS.get(job_id)
    if job is None:
        return JSONResponse({"detail": "job not found"}, status_code=404)
    return job


@app.get("/jobs/{job_id}/events")
async def events(job_id: str):
    job = _job(job_id)
    if isinstance(job, JSONResponse):
        return job

    async def gen():
        # job.events is the replay log; the queue is only a wakeup signal
        # for new events (its payloads are ignored to avoid duplicates).
        idx = 0
        while True:
            while idx < len(job.events):
                ev = job.events[idx]
                idx += 1
                yield {"event": ev["type"],
                       "data": json.dumps(ev, ensure_ascii=False)}
                if ev["type"] in {"done", "failed"}:
                    return
            await job.queue.get()

    return EventSourceResponse(gen())


@app.get("/jobs/{job_id}/report")
async def report(job_id: str):
    job = _job(job_id)
    if isinstance(job, JSONResponse):
        return job
    if job.error:
        return JSONResponse({"detail": job.error}, status_code=500)
    if job.report is None:
        return JSONResponse({"detail": "job still running"}, status_code=409)
    return JSONResponse(job.report.model_dump(mode="json"))


@app.post("/jobs/{job_id}/export")
async def export(job_id: str):
    job = _job(job_id)
    if isinstance(job, JSONResponse):
        return job
    if job.error:
        return JSONResponse({"detail": job.error}, status_code=500)
    if job.report is None:
        return JSONResponse({"detail": "job still running"}, status_code=409)
    try:
        from .export import export_report
        author, initials = _comment_identity(_prefs())
        out = await asyncio.to_thread(
            export_report, job.src_path, job.report,
            None, author, initials)
    except Exception as e:  # noqa: BLE001
        log.exception("export failed for job %s", job.id)
        return JSONResponse({"detail": str(e)}, status_code=500)
    return {"path": str(out)}


# ---------------------------------------------------------------- prefs


@app.get("/prefs")
async def get_prefs() -> dict:
    return _prefs()


@app.put("/prefs")
async def put_prefs(request: Request) -> dict:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"detail": "需要 JSON 对象"}, status_code=400)
    allowed = {"name", "avatar", "comment_author", "comment_initials",
               "onboarded"}
    prefs = _prefs()
    for k in allowed:
        if k in body:
            prefs[k] = body[k]
    if isinstance(prefs.get("avatar"), dict) and \
            isinstance(prefs["avatar"].get("image"), str) and \
            len(prefs["avatar"]["image"]) > 2_000_000:
        return JSONResponse({"detail": "头像图片太大"}, status_code=400)
    Cache(get_settings().cache_path).set(PREFS_KEY, prefs)
    return prefs


# ---------------------------------------------------------------- usage


def _with_cost(rows: list[dict]) -> list[dict]:
    prices = get_settings().llm.prices
    for r in rows:
        p = prices.get(r.get("model") or "")
        if p is None:
            r["cost"] = None
            continue
        cost = (r["prompt"] or 0) / 1e6 * p.input + \
            (r["completion"] or 0) / 1e6 * p.output
        r["cost"] = round(cost, 4)
    return rows


@app.get("/usage")
async def usage() -> dict:
    c = Cache(get_settings().cache_path)
    return {
        "by_doc": _with_cost(c.usage_grouped(["doc", "model"])),
        "by_provider": _with_cost(c.usage_grouped(["provider", "model"])),
        "by_day": _with_cost(c.usage_grouped(["day", "provider", "model"])),
        "totals": _with_cost(c.usage_grouped(["model"])),
    }


# ---------------------------------------------------------------- config


def _toml_set(text: str, section: str, key: str, value: str) -> str:
    """Replace `key = "v"` inside `[section]`, preserving everything else.
    Appends the key (or section) when absent."""
    lines = text.splitlines()
    out: list[str] = []
    in_sec = False
    done = False
    sec_re = re.compile(r"^\s*\[([^\]]+)\]")
    key_re = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*).*$")
    for ln in lines:
        m = sec_re.match(ln)
        if m:
            if in_sec and not done:
                out.append(f'{key} = "{value}"')
                done = True
            in_sec = m.group(1).strip() == section
            out.append(ln)
            continue
        if in_sec and not done:
            km = key_re.match(ln)
            if km:
                out.append(f'{km.group(1)}"{value}"')
                done = True
                continue
        out.append(ln)
    if not done:
        if in_sec:
            out.append(f'{key} = "{value}"')
        else:
            out.append(f"[{section}]")
            out.append(f'{key} = "{value}"')
    return "\n".join(out) + "\n"


@app.get("/config")
async def get_config() -> dict:
    s = get_settings()
    return {
        "base_url": s.llm.cloud.base_url,
        "models": s.llm.models.model_dump(),
        # the two tiers the UI edits; per-task names stay in config.toml
        "fast": s.llm.models.judge,
        "deep": s.llm.models.review,
        "has_api_key": bool(s.dashscope_api_key),
    }


@app.put("/config")
async def put_config(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"detail": "需要 JSON 对象"}, status_code=400)

    from .config import _CONFIG_EXAMPLE_PATH, _CONFIG_PATH, _ENV_PATH

    cfg = _CONFIG_PATH if _CONFIG_PATH.exists() else _CONFIG_EXAMPLE_PATH
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""

    from .config import MODEL_TIERS

    models = body.get("models")
    models = dict(models) if isinstance(models, dict) else {}
    for tier, tasks in MODEL_TIERS.items():
        name = body.get(tier)
        if isinstance(name, str) and name.strip():
            for t in tasks:
                models[t] = name.strip()
    if models:
        valid = set(get_settings().llm.models.model_dump())
        for k, v in models.items():
            if k in valid and isinstance(v, str) and v.strip():
                text = _toml_set(text, "llm.models", k, v.strip())
    base_url = body.get("base_url")
    if isinstance(base_url, str) and base_url.strip().startswith("http"):
        text = _toml_set(text, "llm.cloud", "base_url", base_url.strip())

    try:
        _CONFIG_PATH.write_text(text, encoding="utf-8")
    except OSError as e:
        return JSONResponse({"detail": f"写入 config.toml 失败：{e}"},
                            status_code=500)

    key = body.get("dashscope_api_key")
    if isinstance(key, str) and key.strip():
        env_text = _ENV_PATH.read_text(encoding="utf-8") \
            if _ENV_PATH.exists() else ""
        lines = [ln for ln in env_text.splitlines()
                 if not ln.startswith("DASHSCOPE_API_KEY=")]
        lines.append(f"DASHSCOPE_API_KEY={key.strip()}")
        try:
            _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            return JSONResponse({"detail": f"写入 .env 失败：{e}"},
                                status_code=500)

    get_settings.cache_clear()
    from .llm import client as _llm
    _llm._cloud_client = None
    _llm._cloud_sem = None
    _llm._cache = None
    return await get_config()


@app.get("/models")
async def list_models():
    """Proxy GET {base_url}/models so the settings page can offer the
    model names this API key can actually call."""
    import httpx

    s = get_settings()
    if not s.dashscope_api_key:
        return JSONResponse({"detail": "还没有配置 API Key"},
                            status_code=400)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{s.llm.cloud.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {s.dashscope_api_key}"},
            )
    except httpx.HTTPError as e:
        return JSONResponse({"detail": f"请求失败：{e}"}, status_code=502)
    if r.status_code != 200:
        return JSONResponse({"detail": f"接口返回 {r.status_code}"},
                            status_code=502)
    ids = sorted(
        m.get("id", "") for m in r.json().get("data", []) if m.get("id")
    )
    return {"models": ids}
