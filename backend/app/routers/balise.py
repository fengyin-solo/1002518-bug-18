"""应答器接口：维护应答器，覆盖登记异常、重新固定、办理更换与报文版本保存。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.balise import BaliseService

router = APIRouter(prefix="/api/balise", tags=["应答器"])

service = BaliseService()

LIST_FIELDS = ["应答器编号", "所在位置", "报文版本", "激活距离", "接收电平", "安装方式", "固定状态", "应答器状态"]
STATUSES = ["正常", "报文异常", "松动偏移", "已更换"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按应答器编号检索"),
    status: str | None = Query(default=None, description="正常、报文异常、松动偏移、已更换"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按应答器编号与状态过滤应答器列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 静态路径放在 /{entry_id} 之前，避免「export」被当成应答器编号解析。
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出应答器清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "balise", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条应答器明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"应答器 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条应答器，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="应答器已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """保存报文版本：激活距离超范围或已更换的应答器拒绝写入，并发修改返回 409 且不覆盖原值。"""
    expected_version = payload.values.get("version")
    entry, message, conflict, latest = service.update_entry(
        entry_id, payload.values, expected_version
    )
    if conflict:
        # 409 让提交方明确知道这是并发冲突，而不是普通校验失败；原值与输入都保留。
        return Response(
            content=ActionResult(
                ok=False, message=message, conflict=True, latest=latest
            ).model_dump_json(),
            status_code=status.HTTP_409_CONFLICT,
            media_type="application/json",
        )
    if entry is None:
        return ActionResult(ok=False, message=message, latest=latest)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条应答器执行登记异常、重新固定、办理更换；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
