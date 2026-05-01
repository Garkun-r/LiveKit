import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from config import (
    DIRECTUS_REQUEST_TIMEOUT_SEC,
    DIRECTUS_TOKEN,
    DIRECTUS_URL,
    ROBOT_RUNTIME_PROFILE,
    ROBOT_SETTINGS_CACHE_TTL_SEC,
    ROBOT_SETTINGS_SNAPSHOT_FILE,
    ROBOT_SETTINGS_USE_DIRECTUS,
)

logger = logging.getLogger("robot_settings")

_ROOT_DIR = Path(__file__).resolve().parent.parent


def _as_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_string(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ComponentProfile:
    profile_key: str
    kind: str
    provider: str
    config: dict[str, Any]
    active: bool = True

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ComponentProfile":
        return cls(
            profile_key=_as_string(row.get("profile_key")),
            kind=_as_string(row.get("kind")),
            provider=_as_string(row.get("provider")),
            config=dict(_as_object(row.get("config_json"))),
            active=row.get("active") is not False,
        )


@dataclass(frozen=True)
class ProfileBinding:
    owner_type: str
    owner_key: str
    category: str
    slot: str
    profile_key: str
    active: bool = True

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ProfileBinding":
        return cls(
            owner_type=_as_string(row.get("owner_type")),
            owner_key=_as_string(row.get("owner_key")),
            category=_as_string(row.get("category")),
            slot=_as_string(row.get("slot")),
            profile_key=_as_string(row.get("profile_key")),
            active=row.get("active") is not False,
        )


@dataclass(frozen=True)
class ProjectProfile:
    profile_key: str
    display_name: str
    client_id: str
    did: str
    runtime_key: str
    active: bool = True

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ProjectProfile":
        return cls(
            profile_key=_as_string(row.get("profile_key")),
            display_name=_as_string(row.get("display_name")),
            client_id=_as_string(row.get("client_id")),
            did=_as_string(row.get("did")),
            runtime_key=_as_string(row.get("runtime_key")),
            active=row.get("active") is not False,
        )


@dataclass(frozen=True)
class ComponentSelection:
    category: str
    slot: str
    profile_key: str
    kind: str
    provider: str
    config: dict[str, Any]
    source_owner_type: str
    source_owner_key: str


@dataclass(frozen=True)
class ResolvedRobotSettings:
    requested_runtime_key: str
    effective_runtime_key: str
    project_key: str | None
    project_did: str | None
    source: str
    selections: dict[tuple[str, str], ComponentSelection]

    def component(self, category: str, slot: str = "primary") -> ComponentSelection | None:
        return self.selections.get((category, slot))

    @property
    def llm_primary(self) -> ComponentSelection | None:
        return self.component("llm", "primary")

    @property
    def tts_primary(self) -> ComponentSelection | None:
        return self.component("tts", "primary")

    @property
    def stt_primary(self) -> ComponentSelection | None:
        return self.component("stt", "primary")

    @property
    def turn(self) -> ComponentSelection | None:
        return self.component("turn", "selected")

    @property
    def fallback(self) -> ComponentSelection | None:
        return self.component("fallback", "selected")


class RobotSettingsStore:
    def __init__(
        self,
        *,
        component_profiles: list[ComponentProfile],
        profile_bindings: list[ProfileBinding],
        project_profiles: list[ProjectProfile],
        source: str,
    ) -> None:
        self.component_profiles = {
            profile.profile_key: profile
            for profile in component_profiles
            if profile.active and profile.profile_key
        }
        self.profile_bindings = [
            binding for binding in profile_bindings if binding.active and binding.profile_key
        ]
        self.project_profiles = [
            project for project in project_profiles if project.active and project.profile_key
        ]
        self.source = source

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        source: str,
    ) -> "RobotSettingsStore":
        profile_bindings = [
            ProfileBinding.from_row(row)
            for row in payload.get("profile_bindings", [])
            if isinstance(row, dict)
        ]
        profile_bindings.extend(
            _bindings_from_runtime_profiles(payload.get("runtime_profiles", []))
        )
        profile_bindings.extend(
            _bindings_from_project_profiles(payload.get("project_profiles", []))
        )
        return cls(
            component_profiles=[
                ComponentProfile.from_row(row)
                for row in payload.get("component_profiles", [])
                if isinstance(row, dict)
            ],
            profile_bindings=profile_bindings,
            project_profiles=[
                ProjectProfile.from_row(row)
                for row in payload.get("project_profiles", [])
                if isinstance(row, dict)
            ],
            source=source,
        )

    def resolve(
        self,
        *,
        did: str | None,
        runtime_key: str,
    ) -> ResolvedRobotSettings:
        requested_runtime_key = _as_string(runtime_key) or "base"
        project = self._project_for_did(did)
        effective_runtime_key = self._effective_runtime_key(project, requested_runtime_key)

        selections: dict[tuple[str, str], ComponentSelection] = {}
        for category, slot in (
            ("llm", "primary"),
            ("llm", "backup"),
            ("llm", "third"),
            ("llm_routing", "fast"),
            ("llm_routing", "complex"),
            ("tts", "primary"),
            ("tts", "backup"),
            ("tts", "third"),
            ("stt", "primary"),
            ("stt", "backup"),
            ("stt", "third"),
            ("turn", "selected"),
            ("fallback", "selected"),
        ):
            selection = self._resolve_selection(
                project=project,
                runtime_key=effective_runtime_key,
                category=category,
                slot=slot,
            )
            if selection is not None:
                selections[(category, slot)] = selection

        return ResolvedRobotSettings(
            requested_runtime_key=requested_runtime_key,
            effective_runtime_key=effective_runtime_key,
            project_key=project.profile_key if project else None,
            project_did=project.did if project else None,
            source=self.source,
            selections=selections,
        )

    def _project_for_did(self, did: str | None) -> ProjectProfile | None:
        normalized = _normalize_did(did)
        if not normalized:
            return None
        for project in self.project_profiles:
            if normalized in _split_dids(project.did):
                return project
        return None

    @staticmethod
    def _effective_runtime_key(project: ProjectProfile | None, runtime_key: str) -> str:
        if project is None:
            return runtime_key
        project_runtime = _as_string(project.runtime_key)
        if project_runtime and project_runtime != "base":
            return project_runtime
        return runtime_key

    def _resolve_selection(
        self,
        *,
        project: ProjectProfile | None,
        runtime_key: str,
        category: str,
        slot: str,
    ) -> ComponentSelection | None:
        candidates: list[tuple[str, str]] = []
        if project is not None:
            candidates.append(("project", project.profile_key))
        if runtime_key != "base":
            candidates.append(("runtime", runtime_key))
        candidates.append(("runtime", "base"))

        for owner_type, owner_key in candidates:
            binding = self._binding(owner_type, owner_key, category, slot)
            if binding is None:
                continue
            profile = self.component_profiles.get(binding.profile_key)
            if profile is None:
                logger.warning(
                    "profile binding points to missing component profile",
                    extra={
                        "owner_type": owner_type,
                        "owner_key": owner_key,
                        "category": category,
                        "slot": slot,
                        "profile_key": binding.profile_key,
                    },
                )
                continue
            return ComponentSelection(
                category=category,
                slot=slot,
                profile_key=profile.profile_key,
                kind=profile.kind,
                provider=profile.provider or _as_string(profile.config.get("provider")),
                config=dict(profile.config),
                source_owner_type=owner_type,
                source_owner_key=owner_key,
            )
        return None

    def _binding(
        self,
        owner_type: str,
        owner_key: str,
        category: str,
        slot: str,
    ) -> ProfileBinding | None:
        for binding in self.profile_bindings:
            if (
                binding.owner_type == owner_type
                and binding.owner_key == owner_key
                and binding.category == category
                and binding.slot == slot
            ):
                return binding
        return None


_cached_store: RobotSettingsStore | None = None
_cached_at: float = 0.0


async def resolve_robot_settings_for_call(
    *,
    did: str | None,
    runtime_key: str | None = None,
) -> ResolvedRobotSettings:
    store = await load_robot_settings_store()
    return store.resolve(
        did=did,
        runtime_key=(runtime_key or ROBOT_RUNTIME_PROFILE),
    )


async def load_robot_settings_store(
    *,
    force_refresh: bool = False,
) -> RobotSettingsStore:
    global _cached_at, _cached_store

    now = time.monotonic()
    if (
        not force_refresh
        and _cached_store is not None
        and now - _cached_at <= max(0.0, ROBOT_SETTINGS_CACHE_TTL_SEC)
    ):
        return _cached_store

    if ROBOT_SETTINGS_USE_DIRECTUS and DIRECTUS_URL and DIRECTUS_TOKEN:
        try:
            payload = await _fetch_directus_payload()
            _cached_store = RobotSettingsStore.from_payload(payload, source="directus")
            _cached_at = now
            return _cached_store
        except Exception as e:
            if _cached_store is not None:
                logger.warning(
                    "failed to refresh robot settings from Directus; using cached settings: %s",
                    e,
                )
                return _cached_store
            logger.warning(
                "failed to load robot settings from Directus; trying snapshot: %s",
                e,
            )

    snapshot_store = _load_snapshot_store()
    if snapshot_store is not None:
        _cached_store = snapshot_store
        _cached_at = now
        return snapshot_store

    if _cached_store is not None:
        return _cached_store

    return RobotSettingsStore.from_payload({}, source="empty")


def reset_robot_settings_cache() -> None:
    global _cached_at, _cached_store
    _cached_store = None
    _cached_at = 0.0


async def _fetch_directus_payload() -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=DIRECTUS_URL,
        headers={"Authorization": f"Bearer {DIRECTUS_TOKEN}"},
        timeout=DIRECTUS_REQUEST_TIMEOUT_SEC,
    ) as client:
        (
            component_profiles,
            setting_fields,
            runtime_profiles,
            profile_bindings,
            project_profiles,
        ) = await asyncio.gather(
            _fetch_collection(client, "robot_component_profiles"),
            _fetch_collection(client, "robot_setting_fields"),
            _fetch_collection(client, "robot_runtime_profiles"),
            _fetch_collection(client, "robot_profile_bindings"),
            _fetch_collection(client, "robot_project_profiles"),
        )
    return {
        "component_profiles": component_profiles,
        "setting_fields": setting_fields,
        "runtime_profiles": runtime_profiles,
        "profile_bindings": profile_bindings,
        "project_profiles": project_profiles,
    }


async def _fetch_collection(
    client: httpx.AsyncClient,
    collection: str,
) -> list[dict[str, Any]]:
    response = await client.get(
        f"/items/{collection}",
        params={
            "filter[active][_eq]": "true",
            "limit": "-1",
        },
    )
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _load_snapshot_store() -> RobotSettingsStore | None:
    path = _snapshot_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("failed to load robot settings snapshot: %s", e)
        return None
    if not isinstance(payload, dict):
        return None
    return RobotSettingsStore.from_payload(payload, source=f"snapshot:{path}")


def _snapshot_path() -> Path:
    raw_path = ROBOT_SETTINGS_SNAPSHOT_FILE or "config/robot_settings_snapshot.json"
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return _ROOT_DIR / path


def _normalize_did(value: str | None) -> str:
    return "".join(ch for ch in _as_string(value) if ch.isdigit())


def _split_dids(value: str) -> set[str]:
    dids = set()
    for raw in value.replace(";", ",").split(","):
        normalized = _normalize_did(raw)
        if normalized:
            dids.add(normalized)
    return dids


def _bindings_from_runtime_profiles(rows: Any) -> list[ProfileBinding]:
    bindings: list[ProfileBinding] = []
    iterable = rows if isinstance(rows, list) else []
    for row in iterable:
        if not isinstance(row, dict) or row.get("active") is False:
            continue
        owner_key = _as_string(row.get("runtime_key"))
        if not owner_key:
            continue
        bindings.extend(
            _bindings_from_profile_columns(
                row,
                owner_type="runtime",
                owner_key=owner_key,
            )
        )
    return bindings


def _bindings_from_project_profiles(rows: Any) -> list[ProfileBinding]:
    bindings: list[ProfileBinding] = []
    iterable = rows if isinstance(rows, list) else []
    for row in iterable:
        if not isinstance(row, dict) or row.get("active") is False:
            continue
        owner_key = _as_string(row.get("profile_key"))
        if not owner_key:
            continue
        bindings.extend(
            _bindings_from_profile_columns(
                row,
                owner_type="project",
                owner_key=owner_key,
            )
        )
    return bindings


def _bindings_from_profile_columns(
    row: dict[str, Any],
    *,
    owner_type: str,
    owner_key: str,
) -> list[ProfileBinding]:
    column_map = {
        "llm_profile": ("llm", "primary"),
        "tts_profile": ("tts", "primary"),
        "stt_profile": ("stt", "primary"),
        "turn_profile": ("turn", "selected"),
        "fallback_profile": ("fallback", "selected"),
        "fast_llm_profile": ("llm_routing", "fast"),
        "complex_llm_profile": ("llm_routing", "complex"),
    }
    bindings: list[ProfileBinding] = []
    for column, (category, slot) in column_map.items():
        profile_key = _as_string(row.get(column))
        if not profile_key:
            continue
        bindings.append(
            ProfileBinding(
                owner_type=owner_type,
                owner_key=owner_key,
                category=category,
                slot=slot,
                profile_key=profile_key,
                active=True,
            )
        )
    return bindings
