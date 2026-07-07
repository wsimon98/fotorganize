from __future__ import annotations

from fastapi import APIRouter

from ..services import worker_control

router = APIRouter(prefix="/api/worker", tags=["worker"])


@router.get("/status")
def worker_status():
    return worker_control.status()


@router.post("/start")
def worker_start():
    return worker_control.start()


@router.post("/stop")
def worker_stop():
    return worker_control.stop()
