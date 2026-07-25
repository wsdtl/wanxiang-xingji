"""QQ webhook 脱敏诊断工具。

协议联调需要知道真实 payload 的字段层级，但日志不能泄露 OpenID、消息 ID
或完整原始包。本模块只输出字段结构、身份字段指纹和服务端定义的按钮 data。
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterator


IDENTITY_KEYS = {
    "openid",
    "user_id",
    "user_openid",
    "member_openid",
    "group_member_openid",
    "group_openid",
}
MAX_SCHEMA_FIELDS = 96
MAX_SCHEMA_DEPTH = 6


def safe_payload_summary(payload: object) -> dict[str, str]:
    """生成可写入日志的 payload 摘要，不保留敏感字段原值。"""

    fields = list(_walk_fields(payload))
    schema = ",".join(_schema_item(path, value) for path, _key, value in fields[:MAX_SCHEMA_FIELDS])
    if len(fields) > MAX_SCHEMA_FIELDS:
        schema += f",...(+{len(fields) - MAX_SCHEMA_FIELDS})"

    identities: list[str] = []
    button_values: list[str] = []
    for path, key, value in fields:
        normalized_key = key.lower()
        if normalized_key in IDENTITY_KEYS and _scalar_text(value):
            identities.append(f"{path}:{identity_fingerprint(value)}")
        if normalized_key == "button_data" and _scalar_text(value):
            button_values.append(_short_text(value))

    return {
        "schema": schema or "-",
        "identities": ",".join(dict.fromkeys(identities)) or "-",
        "button_data": " | ".join(dict.fromkeys(button_values)) or "-",
    }


def identity_fingerprint(value: object) -> str:
    """把平台身份转成不可逆短指纹，仅用于跨事件对照。"""

    text = _scalar_text(value)
    if not text:
        return "-"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _walk_fields(value: object, path: str = "$", depth: int = 0) -> Iterator[tuple[str, str, object]]:
    if depth >= MAX_SCHEMA_DEPTH:
        return
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            yield child_path, key, child
            yield from _walk_fields(child, child_path, depth + 1)
        return
    if isinstance(value, list):
        for index, child in enumerate(value[:8]):
            child_path = f"{path}[{index}]"
            yield child_path, str(index), child
            yield from _walk_fields(child, child_path, depth + 1)


def _schema_item(path: str, value: object) -> str:
    if isinstance(value, dict):
        kind = "object"
    elif isinstance(value, list):
        kind = f"list({len(value)})"
    elif value is None:
        kind = "null"
    elif isinstance(value, bool):
        kind = "bool"
    elif isinstance(value, (int, float)):
        kind = type(value).__name__
    else:
        kind = f"str({len(str(value))})"
    return f"{path}:{kind}"


def _scalar_text(value: object) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _short_text(value: object, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
