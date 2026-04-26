"""Rule-based LLM model router.

Where to change behavior:
- Rules and model names live in `routing/model_router_config.yaml`.
- The router returns `reason` and `matched_value` so agent logs can explain why
  a model was selected.

The structure is intentionally simple for this release and can be extended later
with score-based routes, regex rules, and specialist routes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

RouteReason = Literal[
    "forced_fast_flag",
    "full_equals",
    "whole_word",
    "partial",
    "no_match",
]

_WHITESPACE_RE = re.compile(r"\s+")
_TRUE_VALUES = {"1", "true", "yes", "on", "enable", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disable", "disabled"}


@dataclass(frozen=True)
class ModelRouteResult:
    selected_model: str
    model_name: str
    reason: RouteReason
    matched_value: str | None
    normalized_text: str


@dataclass(frozen=True)
class ModelRouterConfig:
    force_fast_flag_field: str
    models: dict[str, str]
    full_equals: tuple[str, ...]
    whole_word: tuple[str, ...]
    partial: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ModelRouterConfig:
        if not isinstance(raw, dict):
            raise ValueError("Model router config must be a mapping")

        force_fast_flag_field = str(
            raw.get("force_fast_flag_field", "fast_model")
        ).strip()
        if not force_fast_flag_field:
            force_fast_flag_field = "fast_model"

        models_raw = raw.get("models", {})
        if not isinstance(models_raw, dict):
            raise ValueError("models must be a mapping with fast/complex keys")

        # Model names are optional in this module because runtime LLM clients
        # can be selected from environment-based provider config.
        fast_model = str(models_raw.get("fast", "")).strip() or "fast"
        complex_model = str(models_raw.get("complex", "")).strip() or "complex"

        return cls(
            force_fast_flag_field=force_fast_flag_field,
            models={"fast": fast_model, "complex": complex_model},
            full_equals=tuple(_to_string_list(raw.get("full_equals", []))),
            whole_word=tuple(_to_string_list(raw.get("whole_word", []))),
            partial=tuple(_to_string_list(raw.get("partial", []))),
        )


def normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    normalized = _WHITESPACE_RE.sub(" ", str(text).lower().strip())
    return normalized


def coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return None


class ModelRouter:
    def __init__(self, config: ModelRouterConfig) -> None:
        self._config = config
        self._full_equals = _normalized_unique(config.full_equals)
        self._whole_word = _normalized_unique(config.whole_word)
        self._partial = _normalized_unique(config.partial)
        self._whole_word_patterns = [
            (value, re.compile(rf"(?<!\w){re.escape(value)}(?!\w)"))
            for value in self._whole_word
            if value
        ]

    @property
    def force_fast_flag_field(self) -> str:
        return self._config.force_fast_flag_field

    @property
    def fast_model_name(self) -> str:
        return self._config.models["fast"]

    @property
    def complex_model_name(self) -> str:
        return self._config.models["complex"]

    def route(
        self, text: str | None, fast_model: bool | None = None
    ) -> ModelRouteResult:
        normalized = normalize_text(text)

        if fast_model is True:
            return self._result(
                selected_model="fast",
                reason="forced_fast_flag",
                matched_value=self.force_fast_flag_field,
                normalized_text=normalized,
            )

        for value in self._full_equals:
            if normalized == value:
                return self._result(
                    selected_model="fast",
                    reason="full_equals",
                    matched_value=value,
                    normalized_text=normalized,
                )

        for value, pattern in self._whole_word_patterns:
            if pattern.search(normalized):
                return self._result(
                    selected_model="fast",
                    reason="whole_word",
                    matched_value=value,
                    normalized_text=normalized,
                )

        for value in self._partial:
            if value and value in normalized:
                return self._result(
                    selected_model="fast",
                    reason="partial",
                    matched_value=value,
                    normalized_text=normalized,
                )

        return self._result(
            selected_model="complex",
            reason="no_match",
            matched_value=None,
            normalized_text=normalized,
        )

    def _result(
        self,
        *,
        selected_model: str,
        reason: RouteReason,
        matched_value: str | None,
        normalized_text: str,
    ) -> ModelRouteResult:
        model_name = self._config.models[selected_model]
        return ModelRouteResult(
            selected_model=selected_model,
            model_name=model_name,
            reason=reason,
            matched_value=matched_value,
            normalized_text=normalized_text,
        )

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> ModelRouter:
        config_path = Path(path)
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid model router config at {config_path}")
        return cls(ModelRouterConfig.from_dict(raw))

    @classmethod
    def from_default_config(cls) -> ModelRouter:
        config_path = Path(__file__).with_name("model_router_config.yaml")
        return cls.from_yaml_file(config_path)


def _to_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Rule groups must be lists")
    return [str(item) for item in value]


def _normalized_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)
