"""应用装载与生命周期测试。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import configure_windows_event_loop, create_app
from launch.config import config
from launch.runtime_guard import runtime_guard


def main() -> None:
    if sys.platform == "win32":
        original_policy = asyncio.get_event_loop_policy()
        try:
            configure_windows_event_loop()
            loop = asyncio.new_event_loop()
            try:
                assert type(loop).__name__ == "_WindowsSelectorEventLoop"
            finally:
                loop.close()
        finally:
            asyncio.set_event_loop_policy(original_policy)

    # 生命周期测试必须能与本地开发服务并行，不能争抢项目真实运行锁。
    original_lock_file = runtime_guard.lock_file
    original_database = config.database
    with TemporaryDirectory() as tmpdir:
        runtime_guard.lock_file = Path(tmpdir) / "server.lock"
        object.__setattr__(
            config,
            "database",
            replace(config.database, path=Path(tmpdir) / "app.db"),
        )
        try:
            with TestClient(create_app()) as client:
                assert client.get("/docs").status_code == 200
                paths = {getattr(route, "path", "") for route in client.app.routes}
                assert "/qq/events" in paths
                assert "/static" in paths
                assert "/battle/{share_id}" in paths
        finally:
            runtime_guard.lock_file = original_lock_file
            object.__setattr__(config, "database", original_database)

    print("application lifespan test passed")


if __name__ == "__main__":
    main()
