# backend/scripts/worker.py
"""
DB-backed background worker.

Key fix:
- DO NOT import backend.app.db (SessionLocal/engine) until AFTER we load .env
  and apply CLI/env overrides. Otherwise SessionLocal points at the wrong DB.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_


POLL_SECONDS_DEFAULT = 1.0
MAX_ATTEMPTS_DEFAULT = 3
RECLAIM_AFTER_SECONDS_DEFAULT = 15 * 60  # 15 minutes


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_dotenv_early() -> None:
    """
    Load .env as early as possible so DATABASE_URL / LLAMA_* are visible.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    # Load .env from CWD or parents; don't override already-set env vars.
    load_dotenv(override=False)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Powertown artifact processing worker")

    p.add_argument(
        "--db",
        default=os.getenv("DATABASE_URL"),
        help="Database URL (overrides DATABASE_URL). Example: sqlite:////abs/path/demo.db",
    )
    p.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.getenv("WORKER_POLL_SECONDS", str(POLL_SECONDS_DEFAULT))),
        help="Seconds to sleep when no jobs are available",
    )
    p.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.getenv("WORKER_MAX_ATTEMPTS", str(MAX_ATTEMPTS_DEFAULT))),
        help="Max attempts per job before marking failed",
    )
    p.add_argument(
        "--reclaim-after-seconds",
        type=int,
        default=int(os.getenv("WORKER_RECLAIM_AFTER_SECONDS", str(RECLAIM_AFTER_SECONDS_DEFAULT))),
        help="If a job is stuck in 'processing' longer than this, move it back to queued",
    )

    # Llama.cpp config
    p.add_argument("--llama-gguf-path", default=os.getenv("LLAMA_GGUF_PATH"))
    p.add_argument("--llama-threads", type=int, default=int(os.getenv("LLAMA_THREADS", "8")))
    p.add_argument("--llama-n-ctx", type=int, default=int(os.getenv("LLAMA_N_CTX", "4096")))
    p.add_argument("--llama-gpu-layers", type=int, default=int(os.getenv("LLAMA_GPU_LAYERS", "0")))
    p.add_argument("--llama-temperature", type=float, default=float(os.getenv("LLAMA_TEMPERATURE", "0.1")))
    p.add_argument("--llama-max-tokens", type=int, default=int(os.getenv("LLAMA_MAX_TOKENS", "700")))
    p.add_argument("--structured-extractor", default=os.getenv("STRUCTURED_EXTRACTOR"))

    return p.parse_args()


def _apply_env(args: argparse.Namespace) -> None:
    """
    Apply CLI overrides to env (CLI wins over .env).
    IMPORTANT: must happen BEFORE importing backend.app.db or processors.registry.
    """
    if args.db:
        os.environ["DATABASE_URL"] = args.db

    if args.llama_gguf_path:
        os.environ["LLAMA_GGUF_PATH"] = args.llama_gguf_path

    os.environ["LLAMA_THREADS"] = str(args.llama_threads)
    os.environ["LLAMA_N_CTX"] = str(args.llama_n_ctx)
    os.environ["LLAMA_GPU_LAYERS"] = str(args.llama_gpu_layers)
    os.environ["LLAMA_TEMPERATURE"] = str(args.llama_temperature)
    os.environ["LLAMA_MAX_TOKENS"] = str(args.llama_max_tokens)

    if args.structured_extractor:
        os.environ["STRUCTURED_EXTRACTOR"] = str(args.structured_extractor)


def _reclaim_stuck_jobs(db, models, reclaim_after_seconds: int) -> int:
    cutoff = _utcnow() - timedelta(seconds=reclaim_after_seconds)

    stuck = (
        db.query(models.ProcessingJob)
        .filter(
            and_(
                models.ProcessingJob.status == "processing",
                models.ProcessingJob.updated_at != None,  # noqa: E711
                models.ProcessingJob.updated_at < cutoff,
            )
        )
        .all()
    )

    n = 0
    for job in stuck:
        job.status = "queued"
        job.updated_at = _utcnow()
        job.last_error = (job.last_error or "")[:1000]
        n += 1

    if n:
        db.commit()
    return n


def _claim_one_job(db, models, max_attempts: int):
    job = (
        db.query(models.ProcessingJob)
        .filter(
            and_(
                models.ProcessingJob.status == "queued",
                models.ProcessingJob.attempts < max_attempts,
            )
        )
        .order_by(models.ProcessingJob.created_at.asc())
        .first()
    )
    if not job:
        return None

    job.status = "processing"
    job.started_at = _utcnow()
    job.updated_at = _utcnow()
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def main() -> None:
    _load_dotenv_early()
    args = _parse_args()
    _apply_env(args)

    # ✅ CRITICAL: import db + models ONLY AFTER env is applied
    from backend.app import models  # noqa: E402
    from backend.app.db import SessionLocal, init_db  # noqa: E402

    # ✅ import processors AFTER env is applied (structured extractor reads env)
    from backend.app.processors.registry import run_job  # noqa: E402

    init_db()

    stop = False

    def _handle_stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    print("worker started")
    print(f"  DATABASE_URL={os.getenv('DATABASE_URL')}")
    if os.getenv("LLAMA_GGUF_PATH"):
        print(f"  LLAMA_GGUF_PATH={os.getenv('LLAMA_GGUF_PATH')}")

    last_reclaim = 0.0
    while not stop:
        db = SessionLocal()
        try:
            now = time.time()
            if now - last_reclaim > 30:
                reclaimed = _reclaim_stuck_jobs(db, models, args.reclaim_after_seconds)
                if reclaimed:
                    print(f"reclaimed {reclaimed} stuck job(s)")
                last_reclaim = now

            job = _claim_one_job(db, models, args.max_attempts)
            if not job:
                time.sleep(args.poll_seconds)
                continue

            try:
                run_job(db, job)

                job.status = "done"
                job.finished_at = _utcnow()
                job.updated_at = _utcnow()
                job.last_error = None
                db.commit()
            except Exception as e:
                job.last_error = str(e)[:2000]
                job.updated_at = _utcnow()
                job.status = "failed" if job.attempts >= args.max_attempts else "queued"
                db.commit()
        finally:
            db.close()

    print("worker stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
