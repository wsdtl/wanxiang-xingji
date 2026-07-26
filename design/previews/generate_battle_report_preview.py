"""Generate the battle report preview through the official party battle pipeline."""

from __future__ import annotations

from datetime import datetime
from itertools import count
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content.presentation import GAME_NAME  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.features.battle_report import build_public_battle_report  # noqa: E402


OUTPUT_PATH = Path(__file__).with_name("battle-report-production.html")
PREVIEW_TIME = datetime(2026, 7, 24, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def build_preview_document() -> dict[str, object]:
    """Run a real party challenge and return its public battle report DTO."""

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "battle-report-preview.db",
            identity_secret="battle-report-preview-secret",
        )
        id_sequence = count(1)
        services.character_creation.workflow.id_factory = (
            lambda kind: f"{kind}:battle-report-preview-{next(id_sequence)}"
        )
        services.database.initialize()
        characters = tuple(
            _create_character(services, index, name)
            for index, name in enumerate(("观潮客", "砺锋客", "司星者"), start=1)
        )
        leader = characters[0]
        created_party = services.party.create(
            "battle-report-preview-party-create",
            leader.id,
            logical_time=PREVIEW_TIME,
        )
        if created_party.status != "created" or created_party.party is None:
            raise RuntimeError(f"preview party creation failed: {created_party.status}")
        party = created_party.party
        for index, character in enumerate(characters[1:], start=1):
            invited = services.party.invite(
                f"battle-report-preview-party-invite-{index}",
                leader.id,
                character.id,
                logical_time=PREVIEW_TIME,
            )
            if invited.request is None:
                raise RuntimeError(f"preview party invite failed: {invited.status}")
            accepted = services.party.accept(
                f"battle-report-preview-party-accept-{index}",
                character.id,
                invited.request.id,
                logical_time=PREVIEW_TIME,
            )
            if accepted.status != "accepted" or accepted.party is None:
                raise RuntimeError(f"preview party accept failed: {accepted.status}")
            party = accepted.party
        selected = services.party_battles.select(
            "battle-report-preview-boss-select",
            party.id,
            leader.id,
            1,
            logical_time=PREVIEW_TIME,
        )
        if selected.status != "selected":
            raise RuntimeError(f"preview boss selection failed: {selected.status}")
        for index, character in enumerate(characters, start=1):
            prepared = services.party_battles.set_ready(
                f"battle-report-preview-ready-{index}",
                party.id,
                character.id,
                True,
                logical_time=PREVIEW_TIME,
            )
            if prepared.status != "ready":
                raise RuntimeError(f"preview party ready failed: {prepared.status}")
        result = services.party_battles.challenge(
            "battle-report-preview-challenge",
            party.id,
            leader.id,
            logical_time=PREVIEW_TIME,
        )
        if result.status not in {"victory", "draw", "defeated"} or not result.share_id:
            raise RuntimeError(f"preview party battle failed: {result.status}")
        report = services.battle_reports.load_public(
            result.share_id,
            logical_time=PREVIEW_TIME,
        )
        if report is None or not report.detail_available or not report.segments:
            raise RuntimeError("official party battle produced no battle report")
        document = build_public_battle_report(report)
        document["game_name"] = GAME_NAME
        return document


def _create_character(services, index: int, name: str):
    subject = f"battle-report-preview-player-{index}"
    evidence = IdentityEvidence(
        f"battle-report-preview-evidence-{index}",
        ExternalIdentity(
            "platform.local",
            "battle-report-preview",
            "identity.user",
            "private",
            subject,
        ),
        (),
        "message.local",
        PREVIEW_TIME,
    )
    created = services.create_character(evidence, requested_name=name)
    if created.status != "created" or created.receipt is None:
        raise RuntimeError(f"preview character creation failed: {created.status}")
    return created.receipt.character


def render_preview(document: dict[str, object]) -> str:
    """Embed only the DTO; layout and behavior remain production assets."""

    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
  <meta name="color-scheme" content="light">
  <title>万象行纪 · 正式战报预览</title>
  <link rel="stylesheet" href="../../static/battle-report/style.css?v=18">
</head>
<body data-mode="compact">
  <main class="report-shell" id="reportRoot" aria-live="polite">
    <section class="loading-state" aria-busy="true">
      <div class="loading-mark" aria-hidden="true"><span></span><span></span><span></span></div>
      <div><h1>战报读取中</h1><p>正在还原战斗事实。</p></div>
    </section>
  </main>
  <script id="battleReportPreviewData" type="application/json">{payload}</script>
  <script type="module" src="../../static/battle-report/app.js?v=18"></script>
</body>
</html>
"""


def main() -> None:
    document = build_preview_document()
    OUTPUT_PATH.write_text(render_preview(document), encoding="utf-8", newline="\n")
    segments = document["detail"]["segments"]
    events = sum(
        len(transition["events"])
        for segment in segments
        for transition in segment["timeline"]
    )
    print(
        f"generated {OUTPUT_PATH.name}: segments={len(segments)} events={events}",
        flush=True,
    )


if __name__ == "__main__":
    main()
