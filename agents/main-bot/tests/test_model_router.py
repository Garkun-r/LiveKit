# ruff: noqa: RUF001

import pytest

from routing.model_router import ModelRouter, ModelRouterConfig


def _router() -> ModelRouter:
    return ModelRouter(
        ModelRouterConfig.from_dict(
            {
                "force_fast_flag_field": "fast_model",
                "models": {
                    "fast": "fast-model-v1",
                    "complex": "complex-model-v1",
                },
                "full_equals": [
                    "да",
                    "алло",
                    "здравствуйте",
                    "здрасте",
                    "кто вы",
                    "да да",
                    "соединить",
                    "да спасибо",
                ],
                "whole_word": ["оператор"],
                "partial": ["операт", "да соед", "спасиб", "менедж", "специалистом"],
            }
        )
    )


def test_fast_model_true_forces_fast() -> None:
    route = _router().route("сколько стоит услуга", fast_model=True)

    assert route.selected_model == "fast"
    assert route.model_name == "fast-model-v1"
    assert route.reason == "forced_fast_flag"


def test_fast_model_false_uses_regular_rules() -> None:
    route = _router().route("да", fast_model=False)

    assert route.selected_model == "fast"
    assert route.reason == "full_equals"
    assert route.matched_value == "да"


@pytest.mark.parametrize(
    ("text", "matched_value"),
    [
        ("да", "да"),
        ("Да", "да"),
        ("  да  ", "да"),
        ("да спасибо", "да спасибо"),
        ("  Да   Спасибо  ", "да спасибо"),
    ],
)
def test_full_equals(text: str, matched_value: str) -> None:
    route = _router().route(text)

    assert route.selected_model == "fast"
    assert route.reason == "full_equals"
    assert route.matched_value == matched_value


@pytest.mark.parametrize(
    ("text", "selected_model", "reason"),
    [
        ("мне нужен оператор", "fast", "whole_word"),
        ("оператор", "fast", "whole_word"),
        ("операторов", "fast", "partial"),
    ],
)
def test_whole_word(text: str, selected_model: str, reason: str) -> None:
    route = _router().route(text)

    assert route.selected_model == selected_model
    assert route.reason == reason


@pytest.mark.parametrize(
    "text",
    [
        "да соедините",
        "спасибо большое",
        "хочу поговорить с менеджером",
        "со специалистом можно?",
    ],
)
def test_partial(text: str) -> None:
    route = _router().route(text)

    assert route.selected_model == "fast"
    assert route.reason == "partial"


@pytest.mark.parametrize(
    "text",
    [
        "сколько стоит услуга",
        "какой у вас график работы",
        "в каком филиале есть эта услуга",
    ],
)
def test_no_match(text: str) -> None:
    route = _router().route(text)

    assert route.selected_model == "complex"
    assert route.model_name == "complex-model-v1"
    assert route.reason == "no_match"
    assert route.matched_value is None


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_input(text: str | None) -> None:
    route = _router().route(text)

    assert route.selected_model == "complex"
    assert route.reason == "no_match"
    assert route.normalized_text == ""
