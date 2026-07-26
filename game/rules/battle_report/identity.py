"""战报身份的内容版本隔离规则。"""


CONTENT_SCOPE_MARKER = ":content:"


def content_scoped_report_id(base_report_id: str, content_fingerprint: str) -> str:
    base = str(base_report_id or "").strip()
    fingerprint = str(content_fingerprint or "").strip()
    if not base or not fingerprint:
        raise ValueError("内容分代战报身份缺少基础身份或内容指纹")
    if CONTENT_SCOPE_MARKER in base:
        raise ValueError("基础战报身份不能重复包含内容分代标记")
    return f"{base}{CONTENT_SCOPE_MARKER}{fingerprint}"


def report_id_matches_content_scope(
    report_id: str,
    content_fingerprint: str,
) -> bool:
    report = str(report_id or "").strip()
    fingerprint = str(content_fingerprint or "").strip()
    return bool(report and fingerprint) and report.endswith(
        f"{CONTENT_SCOPE_MARKER}{fingerprint}"
    )


__all__ = [
    "CONTENT_SCOPE_MARKER",
    "content_scoped_report_id",
    "report_id_matches_content_scope",
]
