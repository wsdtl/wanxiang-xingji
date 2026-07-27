"""世界志命令共用的展示。"""

from __future__ import annotations

from message import Action, DocumentMessage, M
from message.schema import FieldSeparator


def world_lore_overview_message(lore, world_name: str) -> DocumentMessage:
    builder = M.document().section(f"世界志·{world_name}", icon="world")
    if not lore.available:
        return (
            builder.line("尚未在这个世界留下可阅读的行纪")
            .action(Action("world-lore.progress", "查看行纪", "行纪", style="secondary"))
            .build()
        )
    builder.row(
        ("世界进度", f"{lore.percent}%"),
        ("已知记录", f"{len(lore.unlocked_records)}/{len(lore.definition.records)}"),
    )
    builder.line(lore.definition.overview).section("世界记录", icon="notice")
    unlocked_ids = {value.id for value in lore.unlocked_records}
    seen_ids = set(lore.seen_record_ids)
    for index, record in enumerate(lore.definition.records, start=1):
        if record.id not in unlocked_ids:
            status = f"{record.threshold}%解锁"
        elif record.id in seen_ids:
            status = "已阅"
        else:
            status = "新录"
        builder.line(
            f"{index}. ",
            M.command(record.title, f"世界志 {world_name} {index}")
            if record.id in unlocked_ids
            else record.title,
            FieldSeparator(),
            status,
        )
    return builder.note(f"发送：世界志 {world_name} 记录序号").build()


def world_lore_record_message(definition, record, world_name: str) -> DocumentMessage:
    builder = (
        M.document()
        .section(f"{world_name}·{record.title}", icon="world")
        .field("解锁进度", f"{record.threshold}%")
    )
    for paragraph in record.paragraphs:
        builder.line(paragraph)
    return (
        builder.note("世界志记录")
        .action(
            Action(
                "world-lore.back",
                "返回世界志",
                f"世界志 {world_name}",
                style="secondary",
            )
        )
        .build()
    )


def world_lore_failure_message(
    message: str,
    recovery: Action,
) -> DocumentMessage:
    builder = M.document().section("世界志", icon="notice").line(message)
    builder.action(recovery)
    return builder.build()


__all__ = [
    "world_lore_failure_message",
    "world_lore_overview_message",
    "world_lore_record_message",
]
