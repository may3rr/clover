"""本地 FastAPI 服务（127.0.0.1:8765），供 Electron 前端调用。

- POST /analyze：multipart `file` 或表单字段 `path`（本地路径，原地读取，
  不修改），可选 `benchmark`；返回 {job_id}。
- GET /jobs/{id}/events：SSE，先回放已有事件再推送新事件，done/failed
  后关闭。
- GET /jobs/{id}/report：运行中返回 409。
- GET /benchmarks：backend/benchmarks/*.json 的 [{id, name, n_papers}]。
- POST /jobs/{id}/export：{path}。

鉴权：环境变量 CITECHECK_TOKEN 存在时，除 /health 外所有路由要求
X-Citecheck-Token 头或 ?token= 查询参数（EventSource 无法设置请求头）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

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
    if TOKEN and request.url.path != "/health":
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
        except PipelineError as e:
            job.error = str(e)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job.id)
            job.error = str(e)
            emit({"type": "failed", "error": "体检过程中出现内部错误。"})

    job.task = asyncio.create_task(_run())
    return {"job_id": job.id}


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
        out = await asyncio.to_thread(export_report, job.src_path, job.report)
    except Exception as e:  # noqa: BLE001
        log.exception("export failed for job %s", job.id)
        return JSONResponse({"detail": str(e)}, status_code=500)
    return {"path": str(out)}
