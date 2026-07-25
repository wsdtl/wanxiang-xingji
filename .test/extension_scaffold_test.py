"""扩展脚手架必须安全、可重复审计且不污染正式发现。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OPS_SPEC = spec_from_file_location("wanxiang_xingji_ops", ROOT / ".ops" / "__main__.py")
assert OPS_SPEC is not None and OPS_SPEC.loader is not None
OPS_MODULE = module_from_spec(OPS_SPEC)
OPS_SPEC.loader.exec_module(OPS_MODULE)
scaffold_extension = OPS_MODULE.scaffold_extension
audit_extension = OPS_MODULE.audit_extension
audit_all_extensions = OPS_MODULE.audit_all_extensions


def main() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        world_root = root / "game" / "content" / "extensions" / "official"
        content_root = root / "game" / "content" / "extensions" / "official_content"
        world_root.mkdir(parents=True)
        content_root.mkdir(parents=True)

        world = scaffold_extension("world", "fourth_world", root=root)
        content = scaffold_extension("content", "new_armaments", root=root)
        assert world.name == "_fourth_world"
        assert content.name == "_new_armaments"
        assert "WORLD_EXTENSION" in (world / "extension.py").read_text(encoding="utf-8")
        assert "CONTENT_EXTENSION" in (content / "extension.py").read_text(encoding="utf-8")
        assert {value.name for value in world.iterdir()} == {
            "__init__.py",
            "extension.py",
            "world.py",
            "companions.py",
            "enemies.py",
            "disasters.py",
            "lore.py",
            "skin.py",
        }
        assert {value.name for value in content.iterdir()} == {
            "__init__.py",
            "extension.py",
            "content.py",
            "presentation.py",
        }
        world_audit = audit_extension(world, root=root)
        content_audit = audit_extension(content, root=root)
        assert world_audit["valid"] and world_audit["draft"]
        assert content_audit["valid"] and content_audit["draft"]
        all_audit = audit_all_extensions(root=root)
        assert all_audit["valid"]
        assert all_audit["count"] == 2
        assert {report["path"] for report in all_audit["extensions"]} == {
            "game/content/extensions/official/_fourth_world",
            "game/content/extensions/official_content/_new_armaments",
        }

        for invalid in ("FourthWorld", "fourth-world", "_hidden", "class", "世界"):
            try:
                scaffold_extension("world", invalid, root=root)
            except ValueError:
                pass
            else:
                raise AssertionError(f"脚手架接受了非法模块名：{invalid}")

        try:
            scaffold_extension("world", "fourth_world", root=root)
        except FileExistsError:
            pass
        else:
            raise AssertionError("脚手架不得覆盖已有扩展草稿")

        assert (
            spec_from_file_location(
                "draft_world_extension",
                world / "extension.py",
            )
            is not None
        )
    print("extension scaffold tests passed")


if __name__ == "__main__":
    main()
