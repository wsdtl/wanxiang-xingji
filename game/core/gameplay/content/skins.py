"""世界皮肤对稳定内容的展示投影。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ..ids import StableId, stable_id


@dataclass(frozen=True)
class SkinEntry:
    """一个稳定内容键在当前世界中的玩家可见形态。"""

    name: str
    description: str = ""
    icon: str = ""
    aliases: tuple[str, ...] = ()
    compact_name: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("世界皮肤条目缺少名称")
        cleaned = tuple(alias.strip() for alias in self.aliases if alias.strip())
        if len(cleaned) != len(set(cleaned)):
            raise ValueError(f"世界皮肤条目 {self.name} 存在重复别名")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "icon", self.icon.strip())
        object.__setattr__(self, "aliases", cleaned)
        object.__setattr__(self, "compact_name", self.compact_name.strip())


@dataclass(frozen=True)
class SkinPack:
    """一套有版本的世界皮肤。

    皮肤只能保存展示信息。规则数值、掉落概率和业务条件不能进入这里。
    """

    id: StableId
    version: int
    name: str
    description: str = ""
    icon: str = ""
    entries: Mapping[StableId, SkinEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="skin id"))
        if self.version < 1:
            raise ValueError("世界皮肤版本必须从 1 开始")
        name = self.name.strip()
        if not name:
            raise ValueError("世界皮肤缺少名称")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "icon", self.icon.strip())
        normalized: dict[StableId, SkinEntry] = {}
        for key, entry in self.entries.items():
            content_id = stable_id(key, field="skin content id")
            if content_id in normalized:
                raise ValueError(f"世界皮肤条目重复：{content_id}")
            normalized[content_id] = entry
        object.__setattr__(self, "entries", MappingProxyType(normalized))

    def validate(
        self,
        required_ids: set[StableId] | frozenset[StableId],
        known_ids: set[StableId] | frozenset[StableId] | None = None,
    ) -> None:
        """皮肤必须覆盖自身要求的内容，额外条目也必须属于正式内容。"""

        required = set(required_ids)
        known = set(known_ids if known_ids is not None else required_ids)
        actual = set(self.entries)
        missing = sorted(required - actual)
        unknown = sorted(actual - known)
        if missing:
            raise ValueError(f"世界皮肤 {self.id} 缺少条目：{', '.join(missing)}")
        if unknown:
            raise ValueError(f"世界皮肤 {self.id} 含有未知条目：{', '.join(unknown)}")


class SkinProjector:
    """把稳定内容键投影成指定世界皮肤的展示文本。"""

    def __init__(self, pack: SkinPack) -> None:
        self.pack = pack
        aliases: dict[str, StableId] = {}
        for content_id, entry in pack.entries.items():
            for alias in (entry.name, entry.compact_name, *entry.aliases):
                if not alias:
                    continue
                key = self._alias_key(alias)
                owner = aliases.get(key)
                if owner and owner != content_id:
                    raise ValueError(f"世界皮肤别名冲突：{alias} 同时指向 {owner} 和 {content_id}")
                aliases[key] = content_id
        self._aliases = MappingProxyType(aliases)

    def entry(self, content_id: StableId) -> SkinEntry:
        key = stable_id(content_id, field="content id")
        try:
            return self.pack.entries[key]
        except KeyError as exc:
            raise KeyError(f"世界皮肤 {self.pack.id} 没有内容条目：{key}") from exc

    def name(self, content_id: StableId) -> str:
        return self.entry(content_id).name

    def compact_name(self, content_id: StableId) -> str:
        """读取紧凑界面名称；未配置时回退完整名称。"""

        entry = self.entry(content_id)
        return entry.compact_name or entry.name

    def resolve_alias(self, value: object) -> StableId | None:
        return self._aliases.get(self._alias_key(value))

    @staticmethod
    def _alias_key(value: object) -> str:
        return " ".join(str(value or "").strip().casefold().split())


class SkinCatalog:
    """管理任意数量、任意历史版本的世界皮肤。

    目录没有“主世界/备用世界”或固定槽位。调用方使用 ``skin_id`` 与
    ``version`` 精确选择皮肤；省略版本时返回该皮肤的最新版本。
    """

    def __init__(
        self,
        required_content_ids: set[StableId] | frozenset[StableId],
        *,
        scoped_content_ids: Mapping[StableId, frozenset[StableId]] | None = None,
    ) -> None:
        self._required_ids = frozenset(
            stable_id(value, field="required skin content id")
            for value in required_content_ids
        )
        self._scoped_ids = MappingProxyType(
            {
                stable_id(skin_id, field="skin id"): frozenset(
                    stable_id(value, field="skin scoped content id")
                    for value in content_ids
                )
                for skin_id, content_ids in (scoped_content_ids or {}).items()
            }
        )
        self._known_ids = frozenset(
            {
                *self._required_ids,
                *(
                    content_id
                    for content_ids in self._scoped_ids.values()
                    for content_id in content_ids
                ),
            }
        )
        self._packs: dict[tuple[StableId, int], SkinPack] = {}
        self._latest_versions: dict[StableId, int] = {}
        self._name_owners: dict[str, StableId] = {}
        self._frozen = False

    def register(self, pack: SkinPack) -> SkinPack:
        """登记一个皮肤版本，并立即校验内容覆盖和别名冲突。"""

        if self._frozen:
            raise RuntimeError("世界皮肤目录已经冻结，不能在运行期登记皮肤")
        key = (pack.id, pack.version)
        if key in self._packs:
            raise ValueError(f"世界皮肤版本重复：{pack.id}@{pack.version}")
        name_key = self._name_key(pack.name)
        name_owner = self._name_owners.get(name_key)
        if name_owner is not None and name_owner != pack.id:
            raise ValueError(
                f"世界皮肤名称冲突：{pack.name} 同时属于 {name_owner} 和 {pack.id}"
            )
        pack.validate(
            self._required_ids | self._scoped_ids.get(pack.id, frozenset()),
            self._known_ids,
        )
        SkinProjector(pack)
        self._packs[key] = pack
        self._name_owners[name_key] = pack.id
        self._latest_versions[pack.id] = max(
            pack.version,
            self._latest_versions.get(pack.id, 0),
        )
        return pack

    def require(self, skin_id: StableId, version: int | None = None) -> SkinPack:
        """读取指定皮肤版本；不传版本时读取该皮肤最新版本。"""

        key = stable_id(skin_id, field="skin id")
        if version is None:
            try:
                version = self._latest_versions[key]
            except KeyError as exc:
                raise KeyError(f"未知世界皮肤：{key}") from exc
        try:
            return self._packs[(key, int(version))]
        except KeyError as exc:
            raise KeyError(f"未知世界皮肤版本：{key}@{version}") from exc

    def projector(self, skin_id: StableId, version: int | None = None) -> SkinProjector:
        return SkinProjector(self.require(skin_id, version))

    def versions(self, skin_id: StableId) -> tuple[int, ...]:
        key = stable_id(skin_id, field="skin id")
        return tuple(sorted(version for pack_id, version in self._packs if pack_id == key))

    def skin_ids(self) -> tuple[StableId, ...]:
        return tuple(sorted(self._latest_versions))

    @staticmethod
    def _name_key(value: object) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    def freeze(self) -> None:
        if not self._packs:
            raise ValueError("世界皮肤目录不能为空")
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def __len__(self) -> int:
        return len(self._packs)


__all__ = ["SkinCatalog", "SkinEntry", "SkinPack", "SkinProjector"]
