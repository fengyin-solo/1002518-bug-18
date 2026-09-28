"""应答器业务规则：状态流转、字段校验、并发控制与对外展示口径都收在这里。

列表、详情、导出统一经过 ``_present`` 序列化，固定状态/应答器状态都由内部
``status`` 派生，保证任何入口读到的值一致。更新走乐观锁（version)，校验全部
通过后才落数据，保存失败不动原值。
"""
from __future__ import annotations

import math
from typing import Any

from app.store import store

MODULE = "balise"
REQUIRED_FIELDS = ["应答器编号", "所在位置", "报文版本"]
DISPLAY_FIELDS = [
    "应答器编号", "所在位置", "报文版本", "激活距离",
    "接收电平", "安装方式", "固定状态", "应答器状态",
]
FILTER_FIELDS = ["应答器编号", "所在位置", "报文版本"]

STATUS_NORMAL = "正常"
STATUS_ABNORMAL = "报文异常"
STATUS_LOOSE = "松动偏移"
STATUS_REPLACED = "已更换"
STATUS_ORDER = [STATUS_NORMAL, STATUS_ABNORMAL, STATUS_LOOSE, STATUS_REPLACED]

# 应答器上行链路激活距离允许范围（米）。超出范围说明报文与现场设备不匹配，禁止保存。
ACTIVATION_MIN_M = 0.5
ACTIVATION_MAX_M = 10.0

FIXED_STATE_BY_STATUS = {
    STATUS_NORMAL: "牢固",
    STATUS_ABNORMAL: "牢固",
    STATUS_LOOSE: "松动",
    STATUS_REPLACED: "—",  # 已更换的设备不再跟踪固定状态
}


class BaliseService:
    # ---- 读取 ----------------------------------------------------------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        filters: dict[str, str] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            key = keyword.strip()
            rows = [
                row for row in rows
                if any(key in str(row.get(field, "")) for field in FILTER_FIELDS)
            ]
        for field in FILTER_FIELDS:
            value = (filters or {}).get(field, "").strip()
            if value:
                rows = [row for row in rows if value in str(row.get(field, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry) if entry is not None else None

    def _present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """内部记录 -> 对外结构：固定状态/应答器状态一律以 status 为准。"""
        status = str(entry.get("status") or "")
        result: dict[str, Any] = {
            "id": entry.get("id"),
            "status": status,
            "version": int(entry.get("version", 1)),
            "固定状态": FIXED_STATE_BY_STATUS.get(status, "—"),
            "应答器状态": status,
        }
        for field in DISPLAY_FIELDS:
            result.setdefault(field, entry.get(field))
        return result

    # ---- 登记 ----------------------------------------------------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_NORMAL
        entry["version"] = 1
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._present(entry), []

    # ---- 报文版本/激活距离维护 ----------------------------------------

    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        expected_version: Any,
    ) -> tuple[dict[str, Any] | None, str, str]:
        """更新报文版本等字段。

        返回 (记录, 错误类型, 说明)；错误类型为 "" / "invalid" / "conflict"。
        所有校验先于写入执行，任何一项不过都保留原有数据。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, "invalid", f"应答器 {entry_id} 不存在或已归档"

        try:
            expected = int(expected_version)
        except (TypeError, ValueError):
            return None, "invalid", "缺少数据版本标记，请刷新页面后重新打开详情再保存"
        if expected != int(entry.get("version", 1)):
            return (
                None,
                "conflict",
                f"该应答器已被他人修改，当前报文版本为「{entry.get('报文版本')}」，"
                "请刷新查看最新数据后再提交",
            )

        message_version = str(values.get("报文版本", entry.get("报文版本", "")) or "").strip()
        if not message_version:
            return None, "invalid", "报文版本不能为空，保存未生效"

        distance, error = self._parse_distance(values.get("激活距离", entry.get("激活距离")))
        if error:
            return None, "invalid", error

        # 校验全部通过后才写入，失败路径不会改动原记录
        entry["报文版本"] = message_version
        entry["激活距离"] = distance
        entry["version"] = int(entry.get("version", 1)) + 1
        return self._present(entry), "", ""

    def _parse_distance(self, raw: Any) -> tuple[float | None, str]:
        if raw is None or str(raw).strip() == "":
            return None, "激活距离不能为空，保存未生效"
        try:
            distance = float(raw)
        except (TypeError, ValueError):
            return None, f"激活距离「{raw}」不是有效数值，单位为米，请核对后重新保存"
        if not math.isfinite(distance):
            return None, "激活距离必须为有限数值，请核对后重新保存"
        if not ACTIVATION_MIN_M <= distance <= ACTIVATION_MAX_M:
            return (
                None,
                f"激活距离 {distance:g} 米超出允许范围"
                f"（{ACTIVATION_MIN_M:g}~{ACTIVATION_MAX_M:g} 米），该报文版本不允许保存",
            )
        return distance, ""

    # ---- 状态流转 ------------------------------------------------------

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"应答器 {entry_id} 不存在或已归档"

        status = str(entry.get("status") or "")
        if status == STATUS_REPLACED:
            return None, "应答器已办理更换，不再参与固定状态等状态变更"
        if action == "登记异常":
            if status == STATUS_ABNORMAL:
                return None, "应答器已处于报文异常状态，无需重复登记"
            entry["status"] = STATUS_ABNORMAL
        elif action == "重新固定":
            if status != STATUS_LOOSE:
                return None, "应答器当前并非松动偏移状态，无需重新固定"
            entry["status"] = STATUS_NORMAL
        elif action == "办理更换":
            entry["status"] = STATUS_REPLACED
        else:
            return None, f"动作「{action}」不属于应答器可执行范围"

        entry["pending"] = entry["status"] != STATUS_REPLACED
        entry["abnormal"] = entry["status"] == STATUS_ABNORMAL
        return self._present(entry), f"应答器已{action}"
