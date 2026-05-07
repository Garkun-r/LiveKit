import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.webhooks.codex_diagnostics import (  # noqa: E402
    CallContext,
    CodexRunner,
    DiagnosticRule,
    audit_dedupe_key,
    build_codex_prompt,
    extract_final_codex_message,
    parse_codex_report,
    redact_command,
    rule_matches,
    select_matching_rules,
    telegram_payload,
)


def _call(target: str = "cloud") -> CallContext:
    return CallContext.from_payload(
        {
            "agent_name": "main-bot-cloud",
            "room_name": "_79990001122_abcd",
            "started_at": "2026-05-07T12:00:00+00:00",
            "ended_at": "2026-05-07T12:01:00+00:00",
            "sip": {
                "sip_client_number": "+7 (999) 000-11-22",
                "sip_trunk_number": "312388",
                "sip_call_id": "sip-1",
            },
        },
        target=target,
    )


def test_rule_matching_supports_independent_cloud_and_local_targets() -> None:
    cloud_rule = DiagnosticRule(
        id=1,
        enabled=True,
        target="cloud",
        trigger_mode="all_calls",
    )
    local_rule = DiagnosticRule(
        id=2,
        enabled=True,
        target="local",
        trigger_mode="all_calls",
    )

    assert rule_matches(cloud_rule, _call("cloud"), [], trigger="aftercall")
    assert not rule_matches(local_rule, _call("cloud"), [], trigger="aftercall")
    assert rule_matches(local_rule, _call("local"), [], trigger="aftercall")


def test_incident_mode_respects_min_severity() -> None:
    rule = DiagnosticRule(
        id=1,
        enabled=True,
        target="both",
        trigger_mode="incidents",
        min_severity="error",
    )

    assert not rule_matches(
        rule,
        _call(),
        [{"severity": "warning", "incident_type": "slow_response"}],
        trigger="aftercall",
    )
    assert rule_matches(
        rule,
        _call(),
        [{"severity": "error", "incident_type": "agent_session_error"}],
        trigger="aftercall",
    )


def test_xdid_and_caller_modes_normalize_digits() -> None:
    xdid_rule = DiagnosticRule(
        id=1,
        enabled=True,
        target="both",
        trigger_mode="xdid",
        scope_value="+312 388",
    )
    caller_rule = DiagnosticRule(
        id=2,
        enabled=True,
        target="both",
        trigger_mode="caller",
        scope_value="79990001122",
    )

    call = _call()
    assert rule_matches(xdid_rule, call, [], trigger="aftercall")
    assert rule_matches(caller_rule, call, [], trigger="aftercall")


def test_manual_rules_do_not_run_from_aftercall() -> None:
    rule = DiagnosticRule(
        id=1,
        enabled=True,
        target="both",
        trigger_mode="manual",
    )

    assert not rule_matches(rule, _call(), [], trigger="aftercall")
    assert rule_matches(rule, _call(), [], trigger="manual")


def test_select_matching_rules_keeps_multiple_modes() -> None:
    rules = [
        DiagnosticRule(id=1, enabled=True, target="both", trigger_mode="all_calls"),
        DiagnosticRule(id=2, enabled=True, target="both", trigger_mode="incidents"),
        DiagnosticRule(id=3, enabled=False, target="both", trigger_mode="all_calls"),
    ]

    matched = select_matching_rules(
        rules,
        _call(),
        [{"severity": "warning", "incident_type": "slow_response"}],
        trigger="aftercall",
    )

    assert [rule.id for rule in matched] == [1, 2]


def test_dedupe_key_includes_target_rule_and_room() -> None:
    rule = DiagnosticRule(id=42, enabled=True, target="both", trigger_mode="all_calls")

    assert audit_dedupe_key(_call("cloud"), rule) == (
        "cloud:42:all_calls:_79990001122_abcd"
    )


def test_codex_runner_command_is_read_only_ephemeral_json() -> None:
    runner = CodexRunner(repo_dir=Path("/repo"), codex_bin="codex", model="gpt-test")

    command = runner.build_command("diagnose")

    assert command[:7] == [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--json",
        "--output-schema",
    ]
    assert "-C" in command
    assert "/repo" in command
    assert "--model" in command
    assert "gpt-test" in command


def test_prompt_forbids_auto_fix_and_mutating_livekit_commands() -> None:
    prompt = build_codex_prompt(
        call=_call(),
        incidents=[],
        rule=DiagnosticRule(
            id=1, enabled=True, target="both", trigger_mode="all_calls"
        ),
        livekit_snapshot={},
    )

    lowered = prompt.lower()
    assert "diagnose only" in lowered
    assert "do not edit files" in lowered
    assert "do not call mutating livekit commands" in lowered
    assert "untrusted data" in lowered


def test_parse_codex_report_accepts_json_fence() -> None:
    report = parse_codex_report(
        """```json
        {"verdict":"watch","summary":"slow","findings":[],"recommendations":[],"telegram_brief":"slow","markdown":"# slow"}
        ```"""
    )

    assert report["verdict"] == "watch"


def test_extract_final_codex_message_from_jsonl() -> None:
    text = json.dumps({"item": {"type": "agent_message", "text": '{"verdict":"ok"}'}})

    assert extract_final_codex_message(text) == '{"verdict":"ok"}'


def test_redact_command_hides_secret_flag_values() -> None:
    assert redact_command(["lk", "--api-key", "key1", "--api-secret", "secret1"]) == [
        "lk",
        "--api-key",
        "[redacted]",
        "--api-secret",
        "[redacted]",
    ]


def test_telegram_payload_reuses_n8n_friendly_brief_shape() -> None:
    payload = telegram_payload(
        audit_id=7,
        call=_call("local"),
        report={
            "verdict": "needs_attention",
            "summary": "slow response",
            "telegram_brief": "brief",
            "findings": [{"title": "slow", "evidence": "e2e 9000ms"}],
        },
        directus_url="https://jcall.io/directus",
    )

    assert payload["audit_id"] == 7
    assert payload["target"] == "local"
    assert payload["verdict"] == "needs_attention"
    assert payload["telegram_brief"] == "brief"
    assert "e2e 9000ms" in payload["text"]
