"""使用临时数据库启动 Web 游戏台人工验收服务。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    with TemporaryDirectory(prefix="xiuxian4-web-console-") as tmpdir:
        root = Path(tmpdir)

        from launch import config
        from launch.runtime_guard import runtime_guard

        object.__setattr__(
            config,
            "database",
            replace(
                config.database,
                path=root / "game.db",
                message_console_path=root / "message_console.db",
            ),
        )
        object.__setattr__(config, "log", replace(config.log, dir=root, file=root / "preview.log"))
        config.custom["ACCOUNT_IDENTITY_SECRET"] = "preview-identity-secret-32-bytes"
        config.custom["WEB_CONSOLE_USERNAME"] = args.username
        config.custom["WEB_CONSOLE_PASSWORD"] = args.password
        runtime_guard.lock_file = root / "server.lock"

        from game.app import install_message_flow_store
        from game.core.persistence import MessageFlowStore

        install_message_flow_store(MessageFlowStore(root / "message_console.db"))

        from main import configure_windows_event_loop, create_app

        configure_windows_event_loop()

        uvicorn.run(
            create_app(),
            host=args.host,
            port=args.port,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
