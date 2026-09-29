"""应答器业务规则：报文版本维护、固定状态流转与并发冲突校验都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "balise"
REQUIRED_FIELDS = ["应答器编号", "所在位置", "报文版本"]
STATUS_ORDER = ["正常", "报文异常", "松动偏移", "已更换"]
REPLACED_STATUS = "已更换"
LOOSE_STATUS = "松动偏移"
FIXED_STATE = "牢固"
LOOSE_STATE = "松动"
FIX_STATES = [FIXED_STATE, LOOSE_STATE]

# 动作只负责把应答器推向目标状态；「重新固定」处置完成后应回到「正常」。
ACTION_RULES = {"登记异常": "报文异常", "重新固定": "正常", "办理更换": "已更换"}
NEGATIVE_ACTIONS = ["登记异常"]

# 报文版本维护时可写的字段与激活距离允许范围（单位：毫米）。
EDITABLE_FIELDS = ["报文版本", "激活距离"]
ACTIVATION_DISTANCE_MIN = 200
ACTIVATION_DISTANCE_MAX = 1000
DEFAULT_ACTIVATION_DISTANCE = 300


def _sync_status_fields(entry: dict[str, Any]) -> None:
    """让内部 status 与页面展示用的「应答器状态」「待处理」等标记始终是同一个口径。"""
    entry["应答器状态"] = entry["status"]
    entry["pending"] = entry["status"] != REPLACED_STATUS
    entry["abnormal"] = entry["status"] == "报文异常"


class BaliseService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("应答器编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 登记时若带了激活距离就按同一把尺子校验，不带则给默认值，避免脏数据进库。
        if str(values.get("激活距离") or "").strip():
            distance, error = self._parse_distance(values.get("激活距离"))
            if error:
                return None, [error]
            entry["激活距离"] = distance
        else:
            entry["激活距离"] = DEFAULT_ACTIVATION_DISTANCE
        entry["固定状态"] = FIXED_STATE
        entry["status"] = STATUS_ORDER[0]
        entry["version"] = 1
        _sync_status_fields(entry)
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"应答器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于应答器可执行范围"
        # 已更换是终态：固定状态、报文版本都不再参与任何变更。
        if entry.get("status") == REPLACED_STATUS:
            return None, "应答器已办理更换，不再参与固定状态变更与报文版本维护"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 「重新固定」只用来处置松动偏移，其它状态下点它属于误操作，要拦下来说明。
        if action == "重新固定" and entry.get("status") != LOOSE_STATUS:
            return None, f"应答器当前状态为「{entry.get('status')}」，仅松动偏移时才需要重新固定"
        entry["status"] = target
        if action == "重新固定":
            entry["固定状态"] = FIXED_STATE
        _sync_status_fields(entry)
        # 任何落库变更都推进版本号，正在旧版本上编辑的人提交时会收到冲突提示。
        entry["version"] = int(entry.get("version", 1)) + 1
        return entry, f"应答器已{action}"

    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        expected_version: Any,
    ) -> tuple[dict[str, Any] | None, str, bool, dict[str, Any] | None]:
        """保存报文版本。

        返回 (记录, 说明, 是否冲突, 服务端当前记录)：
        - 校验全部通过后才一次性写库，任何一项失败都保留原有数据；
        - expected_version 与库中不一致时判定为并发修改，不覆盖，返回当前记录供页面提示。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"应答器 {entry_id} 不存在或已归档", False, None
        if entry.get("status") == REPLACED_STATUS:
            return None, "应答器已办理更换，报文版本不再允许修改", False, entry
        try:
            expected = int(expected_version)
        except (TypeError, ValueError):
            return None, "缺少数据版本标记，无法确认修改依据，请刷新详情后重试", False, entry
        current_version = int(entry.get("version", 1))
        if expected != current_version:
            latest = dict(entry)
            return (
                None,
                (
                    f"该应答器已被他人修改（当前为第 {current_version} 版，"
                    "你打开的是旧版本），本次保存未覆盖任何数据；"
                    "页面已保留你输入的内容，可查看右侧最新值后刷新再提交"
                ),
                True,
                latest,
            )
        # 先校验后写库：报文版本非空、激活距离必须落在允许范围内。
        message_version = str(values.get("报文版本") or "").strip()
        if not message_version:
            return None, "报文版本不能为空，请填写后再保存", False, entry
        distance, distance_error = self._parse_distance(values.get("激活距离"))
        if distance_error:
            return None, distance_error, False, entry
        entry["报文版本"] = message_version
        entry["激活距离"] = distance
        entry["version"] = current_version + 1
        return entry, "报文版本保存成功", False, entry

    @staticmethod
    def _parse_distance(raw: Any) -> tuple[int | None, str]:
        text = str(raw if raw is not None else "").strip()
        if not text:
            return None, "激活距离不能为空，请填写 200～1000 毫米之间的整数"
        try:
            value = int(text)
        except ValueError:
            return None, f"激活距离「{text}」不是整数，请填写 200～1000 毫米之间的整数"
        if not (ACTIVATION_DISTANCE_MIN <= value <= ACTIVATION_DISTANCE_MAX):
            return (
                None,
                (
                    f"激活距离 {value} 毫米超出允许范围"
                    f"（{ACTIVATION_DISTANCE_MIN}～{ACTIVATION_DISTANCE_MAX} 毫米），"
                    "报文版本不允许保存，请核对后重试"
                ),
            )
        return value, ""
