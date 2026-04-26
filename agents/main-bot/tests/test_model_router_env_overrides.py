import agent
from routing.model_router import ModelRouter, ModelRouterConfig


def _router() -> ModelRouter:
    return ModelRouter(
        ModelRouterConfig.from_dict(
            {
                "force_fast_flag_field": "fast_model",
                "models": {
                    "fast": "yaml-fast-model",
                    "complex": "yaml-complex-model",
                },
                "full_equals": [],
                "whole_word": [],
                "partial": [],
            }
        )
    )


def test_router_model_names_from_yaml_when_env_empty(monkeypatch) -> None:
    monkeypatch.setattr(agent, "MODEL_ROUTER_FAST_MODEL", "")
    monkeypatch.setattr(agent, "MODEL_ROUTER_COMPLEX_MODEL", "")

    resolved = agent._resolve_router_model_names(_router())

    assert resolved == {
        "fast": "yaml-fast-model",
        "complex": "yaml-complex-model",
    }


def test_router_model_names_from_env_when_present(monkeypatch) -> None:
    monkeypatch.setattr(agent, "MODEL_ROUTER_FAST_MODEL", "env-fast-model")
    monkeypatch.setattr(agent, "MODEL_ROUTER_COMPLEX_MODEL", "env-complex-model")

    resolved = agent._resolve_router_model_names(_router())

    assert resolved == {
        "fast": "env-fast-model",
        "complex": "env-complex-model",
    }
