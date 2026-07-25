"""只在受控目录中发现冻结扩展描述，不接受导入副作用注册。"""

from __future__ import annotations

from importlib import import_module
import pkgutil

from .catalog import ExtensionCatalog
from .models import ContentExtension, WorldExtension


_CONTENT_ROOT = "game.content.extensions.official_content"
_WORLD_ROOT = "game.content.extensions.official"


def discover_extension_catalog() -> ExtensionCatalog:
    return ExtensionCatalog(
        content=_discover(_CONTENT_ROOT, "CONTENT_EXTENSION", ContentExtension),
        worlds=_discover(_WORLD_ROOT, "WORLD_EXTENSION", WorldExtension),
    )


def _discover(package_name: str, export_name: str, expected_type: type):
    package = import_module(package_name)
    paths = tuple(getattr(package, "__path__", ()))
    discovered = []
    for module in sorted(pkgutil.iter_modules(paths), key=lambda value: value.name):
        if module.name.startswith("_"):
            continue
        descriptor_module = import_module(
            f"{package_name}.{module.name}.extension"
        )
        try:
            descriptor = getattr(descriptor_module, export_name)
        except AttributeError as exc:
            raise AttributeError(
                f"扩展 {descriptor_module.__name__} 必须导出 {export_name}"
            ) from exc
        if not isinstance(descriptor, expected_type):
            raise TypeError(
                f"扩展 {descriptor_module.__name__}.{export_name} 类型不正确"
            )
        discovered.append(descriptor)
    return tuple(discovered)


__all__ = ["discover_extension_catalog"]
