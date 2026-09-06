"""盯盘 API：/api/monitor/* —— 任务 CRUD + 开关 + 信号查询。"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from monitor.runtime import load_check

router = APIRouter(prefix="/api/monitor")


class TaskCreate(BaseModel):
    name: str
    symbol: str
    script: str
    interval_sec: int = 60
    notify: int = 1
    description: str = ""


class TaskUpdate(BaseModel):
    name: str | None = None
    symbol: str | None = None
    script: str | None = None
    interval_sec: int | None = None
    notify: int | None = None
    description: str | None = None


def _store(request: Request):
    return request.app.state.stores.monitor


def _validate_script(script: str) -> None:
    try:
        load_check(script)
    except (ValueError, SyntaxError) as e:
        raise HTTPException(400, f"script 无效: {e}")


@router.get("/tasks")
def list_tasks(request: Request):
    return {"items": _store(request).list_tasks()}


@router.post("/tasks")
def create_task(request: Request, body: TaskCreate):
    _validate_script(body.script)
    task_id = _store(request).add_task(
        body.name, body.symbol, body.script,
        interval_sec=body.interval_sec, notify=body.notify,
        description=body.description)
    return {"id": task_id}


@router.put("/tasks/{task_id}")
def update_task(request: Request, task_id: int, body: TaskUpdate):
    store = _store(request)
    if store.get_task(task_id) is None:
        raise HTTPException(404, f"task {task_id} 不存在")
    if body.script is not None:
        _validate_script(body.script)
    store.update_task(task_id, name=body.name, symbol=body.symbol,
                      script=body.script, interval_sec=body.interval_sec,
                      notify=body.notify, description=body.description)
    return {"ok": True}


@router.post("/tasks/{task_id}/toggle")
def toggle_task(request: Request, task_id: int):
    store = _store(request)
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(404, f"task {task_id} 不存在")
    enabled = 0 if task["enabled"] else 1
    store.set_enabled(task_id, enabled)
    return {"enabled": enabled}


@router.delete("/tasks/{task_id}")
def delete_task(request: Request, task_id: int):
    store = _store(request)
    if store.get_task(task_id) is None:
        raise HTTPException(404, f"task {task_id} 不存在")
    store.delete_task(task_id)
    return {"ok": True}


@router.get("/signals")
def list_signals(request: Request, task_id: int | None = None, limit: int = 200):
    return {"items": _store(request).list_signals(task_id=task_id, limit=limit)}
