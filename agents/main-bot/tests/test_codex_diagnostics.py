import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.webhooks.codex_diagnostics import (  # noqa: E402
    CallContext,
    CodexRunner,
    DiagnosticRule,
    DirectusClient,
    aftercall_execution_url_from_payload,
    audit_dedupe_key,
    build_codex_prompt,
    build_livekit_snapshot_commands,
    collect_diagnostic_signals,
    directus_audit_report_url,
    extract_final_codex_message,
    format_call_time,
    full_report_payload,
    full_report_text,
    incident_time_filters,
    parse_codex_report,
    raw_log_time_filters,
    redact_command,
    render_diagnostic_prompt_template,
    report_markdown,
    rule_matches,
    run_diagnostics,
    select_matching_rules,
    split_telegram_text,
    telegram_payload,
    telegram_skip_status,
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


def test_directus_rule_casts_string_id_to_int() -> None:
    rule = DiagnosticRule.from_directus(
        {
            "id": "7",
            "enabled": True,
            "target": "cloud",
            "trigger_mode": "all_calls",
        }
    )

    assert rule.id == 7


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
    manual_rule = DiagnosticRule(
        id=1,
        enabled=True,
        target="both",
        trigger_mode="manual",
    )
    all_calls_rule = DiagnosticRule(
        id=2,
        enabled=True,
        target="both",
        trigger_mode="all_calls",
    )

    assert not rule_matches(manual_rule, _call(), [], trigger="aftercall")
    assert rule_matches(manual_rule, _call(), [], trigger="manual")
    assert not rule_matches(all_calls_rule, _call(), [], trigger="manual")


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


def test_incident_time_filters_pad_call_window() -> None:
    filters = incident_time_filters(_call())

    assert filters["filter[created_at][_gte]"].startswith("2026-05-07T11:55:00")
    assert filters["filter[created_at][_lte]"].startswith("2026-05-07T12:11:00")


def test_raw_log_time_filters_cover_call_and_short_tail() -> None:
    filters = raw_log_time_filters(_call())

    assert filters["filter[event_time][_gte]"].startswith("2026-05-07T11:59:00")
    assert filters["filter[event_time][_lte]"].startswith("2026-05-07T12:04:00")


class _IncidentLookupDirectus(DirectusClient):
    def __init__(self) -> None:
        self.calls = 0

    def _request(self, method: str, path: str, **kwargs):
        self.calls += 1
        assert method == "GET"
        assert path == "/items/robot_incidents"
        params = kwargs["params"]
        assert params["filter[environment][_eq]"] == "cloud"
        assert params["filter[room_name][_eq]"] == "_79990001122_abcd"
        assert "filter[caller_phone][_eq]" not in params
        assert "filter[did][_eq]" not in params
        assert params["filter[created_at][_gte]"].startswith("2026-05-07T11:55:00")
        assert params["filter[created_at][_lte]"].startswith("2026-05-07T12:11:00")
        return [
            {
                "id": 1,
                "created_at": "2026-05-07T12:00:05+00:00",
                "incident_type": "room_error",
            }
        ]


class _NoIncidentLookupDirectus(DirectusClient):
    def __init__(self) -> None:
        pass

    def _request(self, method: str, path: str, **kwargs):
        raise AssertionError("incident lookup should require room_name")


def test_directus_incident_lookup_uses_room_name_only() -> None:
    directus = _IncidentLookupDirectus()
    incidents = directus.list_incidents_for_call(_call())

    assert directus.calls == 1
    assert [item["id"] for item in incidents] == [1]


def test_directus_incident_lookup_skips_without_room_name() -> None:
    call = CallContext.from_payload(
        {
            **_call().payload,
            "room_name": "",
        },
        target="cloud",
    )

    assert _NoIncidentLookupDirectus().list_incidents_for_call(call) == []


class _RuntimeContextDirectus(DirectusClient):
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []

    def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        params = kwargs["params"]
        if path == "/items/robot_call_sessions":
            assert params["filter[room_name][_eq]"] == "_79990001122_abcd"
            return [
                {
                    "id": 23834,
                    "room_name": "_79990001122_abcd",
                    "duration_sec": 11.4,
                    "close_reason": "CloseReason.PARTICIPANT_DISCONNECTED",
                    "transcript_items": [],
                    "tag_events": [],
                    "usage_updates": [],
                    "metrics_summary": {
                        "transcript_count": 0,
                        "tag_event_count": 0,
                    },
                    "payload": {"metrics_events": [{"type": "llm_metrics"}]},
                }
            ]
        if path == "/items/robot_call_raw_logs":
            assert params["filter[call_session][_eq]"] == "23834"
            return [
                {
                    "id": 1,
                    "event_time": "2026-05-07T12:00:02+00:00",
                    "level": "INFO",
                    "logger_name": "agent",
                    "message": "prompt resolved",
                    "payload": {"extras": {"room": "_79990001122_abcd"}},
                },
                {
                    "id": 2,
                    "event_time": "2026-05-07T12:00:04+00:00",
                    "level": "INFO",
                    "logger_name": "agent",
                    "message": "user state changed",
                    "payload": {"extras": {"new_state": "speaking"}},
                },
            ]
        raise AssertionError(f"unexpected request: {method} {path}")


def test_directus_fetches_call_session_and_raw_logs_for_codex_context() -> None:
    directus = _RuntimeContextDirectus()
    call_session = directus.fetch_call_session_for_call(_call())
    raw_logs = directus.fetch_raw_logs_for_call(_call(), call_session=call_session)

    assert call_session["status"] == "found"
    assert call_session["session"]["id"] == 23834
    assert raw_logs["status"] == "found"
    assert raw_logs["query_source"] == "call_session"
    assert raw_logs["count"] == 2
    assert raw_logs["rows"][0]["message"] == "prompt resolved"


class _RoomRawLogDirectus(DirectusClient):
    def __init__(self) -> None:
        pass

    def _request(self, method: str, path: str, **kwargs):
        params = kwargs["params"]
        assert path == "/items/robot_call_raw_logs"
        assert params["filter[room_name][_eq]"] == "_79990001122_abcd"
        assert params["filter[event_time][_gte]"].startswith("2026-05-07T11:59:00")
        return []


def test_directus_raw_logs_fall_back_to_room_name_without_session() -> None:
    raw_logs = _RoomRawLogDirectus().fetch_raw_logs_for_call(_call(), call_session={})

    assert raw_logs["status"] == "not_found"
    assert raw_logs["query_source"] == "room_name"


def test_collect_diagnostic_signals_marks_no_dialog_root_cause_focus() -> None:
    call = CallContext.from_payload(
        {
            **_call().payload,
            "duration_sec": 11.4,
            "summary": {"transcript_count": 0, "tag_event_count": 0},
            "close": {"reason": "CloseReason.PARTICIPANT_DISCONNECTED"},
        },
        target="cloud",
    )
    signals = collect_diagnostic_signals(
        call=call,
        incidents=[],
        call_session={
            "status": "found",
            "session": {
                "id": 23834,
                "transcript_items": [],
                "tag_events": [],
                "metrics_summary": {
                    "transcript_count": 0,
                    "tag_event_count": 0,
                },
                "payload": {"metrics_events": [{"type": "llm_metrics"}]},
            },
        },
        raw_logs={
            "status": "found",
            "rows": [
                {"level": "INFO", "message": "prompt resolved"},
                {"level": "INFO", "message": "using Deepgram STT provider"},
                {"level": "INFO", "message": "tts synthesis warmup completed"},
                {
                    "level": "INFO",
                    "message": "user state changed",
                    "extras": {"new_state": "speaking"},
                },
                {"level": "INFO", "message": "local VAD end of speech"},
                {
                    "level": "INFO",
                    "message": "closing agent session due to participant disconnect",
                },
            ],
        },
        livekit_snapshot={
            "commands": [
                {
                    "stdout": (
                        "_79990001122_abcd Participants=2\n"
                        "EGRESS_ACTIVE _79990001122_abcd"
                    )
                }
            ]
        },
    )

    assert signals["short_call_no_dialog"] is True
    assert signals["prompt_resolved_log_seen"] is True
    assert signals["tts_warmup_seen"] is True
    assert signals["user_speech_state_seen"] is True
    assert signals["initial_greeting_playback_log_seen"] is False
    assert signals["room_seen_in_livekit_snapshot"] is True
    assert "root_cause_no_dialog" in signals["analysis_focus"]
    assert "verify_initial_greeting_or_first_reply" in signals["analysis_focus"]


def test_telegram_policy_can_skip_n8n_handoff() -> None:
    silent = DiagnosticRule(
        id=1,
        enabled=True,
        target="both",
        trigger_mode="all_calls",
        telegram_policy="silent",
    )
    critical_only = DiagnosticRule(
        id=2,
        enabled=True,
        target="both",
        trigger_mode="all_calls",
        telegram_policy="critical_only",
    )

    assert telegram_skip_status(silent, {"verdict": "critical"}) == "skipped:silent"
    assert telegram_skip_status(
        critical_only, {"verdict": "needs_attention"}
    ) == "skipped:critical_only"
    assert telegram_skip_status(critical_only, {"verdict": "critical"}) is None


def test_codex_runner_command_is_read_only_ephemeral_json() -> None:
    runner = CodexRunner(repo_dir=Path("/repo"), codex_bin="codex", model="gpt-test")

    command = runner.build_command("diagnose")

    assert command[:5] == [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
    ]
    assert "--json" in command
    assert "--output-schema" in command
    assert "-C" in command
    assert "/repo" in command
    assert "--skip-git-repo-check" in command
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
    assert "russian" in lowered
    assert "паузы и задержки" in lowered
    assert "ошибки и инциденты" in lowered
    assert "exact tag/value/action" in lowered
    assert "previous assistant phrase" in lowered
    assert "missing_evidence" in lowered
    assert "prompt_context.rendered_prompt" in prompt
    assert "raw_logs" in prompt
    assert "root-cause audit" in lowered
    assert "do not confuse tts warmup" in lowered
    assert "no-dialog call longer than five seconds" in lowered


def test_parse_codex_report_accepts_json_fence() -> None:
    report = parse_codex_report(
        """```json
        {"verdict":"watch","summary":"slow","findings":[],"recommendations":[],"telegram_brief":"slow","markdown":"# slow"}
        ```"""
    )

    assert report["verdict"] == "watch"


def test_report_markdown_fallback_is_readable_russian() -> None:
    markdown = report_markdown(
        {
            "verdict": "needs_attention",
            "summary": "Робот не ответил на вопрос клиента.",
            "findings": [
                {
                    "title": "Нет ответа по адресу",
                    "severity": "warning",
                    "plain_explanation": (
                        "Клиент спросил адрес, но робот не дал понятный ответ."
                    ),
                    "stage": "основной вопрос клиента",
                    "event_time_or_turn": "после вопроса клиента про адрес",
                    "exact_detail": "адрес не найден в базе знаний",
                    "source_of_truth": "prompt_context.rendered_prompt",
                    "evidence": "Клиент спросил адрес.",
                    "why_it_matters": "Клиент не получил нужную информацию.",
                    "suspected_cause": "Ответ не найден в базе.",
                    "recommendation": "Проверить запись адреса.",
                    "implementation_idea": "Добавить адрес в Directus и покрыть lookup тестом.",
                    "missing_evidence": "Нет сырых логов поиска по базе.",
                }
            ],
            "recommendations": ["Добавить адрес в базу знаний."],
        }
    )

    assert "Диагностический отчет" in markdown
    assert "Паузы и задержки" in markdown
    assert "Ошибки и инциденты" in markdown
    assert "Что произошло простыми словами: Клиент спросил адрес" in markdown
    assert "Где в звонке: основной вопрос клиента" in markdown
    assert "Техническая деталь: адрес не найден в базе знаний" in markdown
    assert "Источник проверки: prompt_context.rendered_prompt" in markdown
    assert "Что сделать: Добавить адрес в Directus" in markdown
    assert "Гарантия безопасности" in markdown
    assert "Evidence:" not in markdown


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


def test_local_livekit_snapshot_uses_existing_livekit_env(monkeypatch) -> None:
    monkeypatch.delenv("CODEX_DIAGNOSTICS_LK_LOCAL_SSH_TARGET", raising=False)
    monkeypatch.delenv("CODEX_DIAGNOSTICS_LK_LOCAL_URL", raising=False)
    monkeypatch.delenv("CODEX_DIAGNOSTICS_LK_LOCAL_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_DIAGNOSTICS_LK_LOCAL_API_SECRET", raising=False)
    monkeypatch.setenv("LIVEKIT_URL", "http://127.0.0.1:7880")
    monkeypatch.setenv("LIVEKIT_API_KEY", "local-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "local-secret")

    commands, missing = build_livekit_snapshot_commands("local")

    assert missing == []
    assert commands[0][:7] == [
        "lk",
        "--url",
        "http://127.0.0.1:7880",
        "--api-key",
        "local-key",
        "--api-secret",
        "local-secret",
    ]


def test_local_livekit_snapshot_can_run_through_asterisk_ssh(monkeypatch) -> None:
    monkeypatch.setenv(
        "CODEX_DIAGNOSTICS_LK_LOCAL_SSH_TARGET", "root@87.226.145.66"
    )
    monkeypatch.setenv("CODEX_DIAGNOSTICS_LK_LOCAL_SSH_PORT", "39001")
    monkeypatch.setenv("CODEX_DIAGNOSTICS_LK_LOCAL_SSH_KEY", "/root/.ssh/id_rsa_n8n")

    commands, missing = build_livekit_snapshot_commands("local")

    assert missing == []
    assert commands[0][:7] == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-i",
        "/root/.ssh/id_rsa_n8n",
    ]
    assert "-p" in commands[0]
    assert "39001" in commands[0]
    assert "root@87.226.145.66" in commands[0]
    assert "LIVEKIT_API_KEY" in commands[0][-1]


def test_cloud_livekit_snapshot_prefers_explicit_cloud_credentials(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_DIAGNOSTICS_LK_CLOUD_URL", "wss://cloud.livekit")
    monkeypatch.setenv("CODEX_DIAGNOSTICS_LK_CLOUD_API_KEY", "cloud-key")
    monkeypatch.setenv("CODEX_DIAGNOSTICS_LK_CLOUD_API_SECRET", "cloud-secret")
    monkeypatch.setenv("CODEX_DIAGNOSTICS_LK_CLOUD_PROJECT", "jcallio")

    commands, missing = build_livekit_snapshot_commands("cloud")

    assert missing == []
    assert commands[0][:7] == [
        "lk",
        "--url",
        "wss://cloud.livekit",
        "--api-key",
        "cloud-key",
        "--api-secret",
        "cloud-secret",
    ]
    assert "--project" not in commands[0]


def test_directus_audit_report_url_points_to_item_page(monkeypatch) -> None:
    assert directus_audit_report_url(
        directus_url="https://jcall.io/directus", audit_id=7
    ) == "https://jcall.io/directus/admin/content/robot_call_audits/7"

    monkeypatch.setenv(
        "CODEX_DIAGNOSTICS_DIRECTUS_APP_URL", "https://jcall.io/directus/admin"
    )
    assert directus_audit_report_url(
        directus_url="https://api.example/directus", audit_id=8
    ) == "https://jcall.io/directus/admin/content/robot_call_audits/8"


def test_call_time_and_aftercall_execution_url_are_readable(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_DIAGNOSTICS_REPORT_TZ", "Europe/Kaliningrad")

    assert format_call_time(
        started_at="2026-05-07T05:08:02+00:00",
        ended_at="2026-05-07T05:08:28+00:00",
        duration_sec=25.3,
    ) == (
        "начало 2026-05-07 07:08:02 (Europe/Kaliningrad), "
        "конец 2026-05-07 07:08:28 (Europe/Kaliningrad), "
        "длительность 25.3 сек"
    )
    assert aftercall_execution_url_from_payload(
        {"codex_diagnostics_aftercall_execution_id": "37107"}
    ) == "https://n8n.jcall.io/workflow/yj1KNjeuDOcJZNSS/executions/37107"
    assert aftercall_execution_url_from_payload(
        {
            "codex_diagnostics": {
                "aftercall_execution_url": "https://n8n.example/execution/1"
            }
        }
    ) == "https://n8n.example/execution/1"


def test_render_diagnostic_prompt_template_uses_call_time() -> None:
    rendered = render_diagnostic_prompt_template(
        "base\n{{CURRENT_DATETIME_BLOCK}}\nknowledge",
        timezone_name="Europe/Kaliningrad",
        started_at="2026-05-08T08:38:25+00:00",
    )

    assert "8 мая 2026 г." in rendered  # noqa: RUF001
    assert "- День недели: пятница" in rendered
    assert "- Время: 10:00" in rendered
    assert "knowledge" in rendered


class _PromptContextDirectus(DirectusClient):
    def __init__(self) -> None:
        pass

    def _request(self, method: str, path: str, **kwargs):
        assert method == "GET"
        assert path == "/items/client_prompt_cache"
        assert kwargs["params"]["filter[caller_id][_eq]"] == "312388"
        return [
            {
                "id": 5,
                "caller_id": "312388",
                "client_id": 9,
                "prompt_template": (
                    "<knowledge_base>\n"
                    "9 мая выходной.\n"
                    "{{CURRENT_DATETIME_BLOCK}}\n"
                    "</knowledge_base>"
                ),
                "timezone": "Europe/Kaliningrad",
                "source_hash": "abc",
                "date_updated": "2026-05-08T08:00:00+00:00",
            }
        ]


def test_fetch_prompt_context_uses_directus_cache() -> None:
    context = _PromptContextDirectus().fetch_prompt_context_for_call(_call())

    assert context["status"] == "found"
    assert context["source"] == "directus:client_prompt_cache"
    assert context["caller_id"] == "312388"
    assert context["client_id"] == 9
    assert "9 мая выходной" in context["rendered_prompt"]
    assert "7 мая 2026 г." in context["rendered_prompt"]  # noqa: RUF001


def test_telegram_payload_uses_russian_brief_and_report_link() -> None:
    call = CallContext.from_payload(
        {
            **_call("local").payload,
            "duration_sec": 61,
            "codex_diagnostics_aftercall_execution_id": "123",
        },
        target="local",
    )
    payload = telegram_payload(
        audit_id=7,
        call=call,
        report={
            "verdict": "needs_attention",
            "summary": "медленный ответ",
            "telegram_brief": "old brief",
            "findings": [
                {
                    "title": "Медленный ответ",
                    "plain_explanation": (
                        "Робот ответил заметно позже, чем должен был."
                    ),
                    "stage": "квалификация заявки",
                    "event_time_or_turn": "после вопроса робота про задачу клиента",
                    "exact_detail": "e2e latency 9000ms",
                    "source_of_truth": "metrics_events",
                    "evidence": "e2e 9000ms",
                    "implementation_idea": "Проверить slow_response threshold и трассировку turn metrics.",
                }
            ],
        },
        directus_url="https://jcall.io/directus",
    )

    assert payload["audit_id"] == 7
    assert payload["target"] == "local"
    assert payload["verdict"] == "needs_attention"
    assert payload["directus_report_url"] == (
        "https://jcall.io/directus/admin/content/robot_call_audits/7"
    )
    assert payload["report_url"] == payload["directus_report_url"]
    assert payload["button_text"] == "отправить полный отчет"
    assert payload["callback_data"] == "codex_full_report:7"
    assert payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == (
        "codex_full_report:7"
    )
    assert "Вердикт: требует внимания" in payload["telegram_brief"]
    assert "Звонок: начало 2026-05-07 14:00:00" in payload["telegram_brief"]
    assert (
        "Клиент: +7 (999) 000-11-22 | DID/xDID: 312388 | локальный"
        in payload["telegram_brief"]
    )
    assert "Прогон aftercall: https://n8n.jcall.io/workflow/yj1KNjeuDOcJZNSS/executions/123" in payload["telegram_brief"]
    assert "Полный отчет: https://jcall.io/directus/admin/content/robot_call_audits/7" in payload["telegram_brief"]
    assert "Итог:" in payload["telegram_brief"]
    assert "Главное:" in payload["telegram_brief"]
    assert "1. Медленный ответ" in payload["telegram_brief"]
    assert "   Смысл: Робот ответил заметно позже" in payload["telegram_brief"]
    assert (
        "   Где: квалификация заявки; после вопроса робота про задачу клиента."
        in payload["telegram_brief"]
    )
    assert "   Почему верю: e2e 9000ms e2e latency 9000ms." in payload["telegram_brief"]
    assert "   Что сделать: Проверить slow_response threshold" in payload["telegram_brief"]
    assert "   Источник:" not in payload["telegram_brief"]
    assert "e2e 9000ms" in payload["text"]


def test_full_report_text_includes_metadata_report_and_directus_link() -> None:
    text = full_report_text(
        {
            "id": 7,
            "target": "cloud",
            "verdict": "needs_attention",
            "room_name": "room-1",
            "caller_phone": "79990001122",
            "did": "312388",
            "started_at": "2026-05-07T12:00:00+00:00",
            "ended_at": "2026-05-07T12:01:00+00:00",
            "incident_ids": [1, 2],
            "input_payload": {
                "duration_sec": 60,
                "codex_diagnostics_aftercall_execution_id": "321",
            },
            "report_markdown": "## Паузы и задержки\nДлинных пауз нет.",  # noqa: RUF001
        },
        directus_url="https://jcall.io/directus",
    )

    assert "Полный диагностический отчет" in text
    assert "Вердикт: требует внимания" in text
    assert "Время звонка: начало 2026-05-07 14:00:00" in text
    assert "Прогон aftercall: https://n8n.jcall.io/workflow/yj1KNjeuDOcJZNSS/executions/321" in text
    assert "Инциденты: 1, 2" in text
    assert "https://jcall.io/directus/admin/content/robot_call_audits/7" in text
    assert "Длинных пауз нет." in text


def test_split_telegram_text_chunks_long_reports() -> None:
    chunks = split_telegram_text("я" * 3700, limit=1000)

    assert len(chunks) == 4
    assert all(len(chunk) <= 1000 for chunk in chunks)


class _FullReportDirectus:
    url = "https://jcall.io/directus"

    def get_audit(self, audit_id: int) -> dict:
        assert audit_id == 7
        return {
            "id": 7,
            "target": "local",
            "verdict": "watch",
            "report_markdown": "## Ошибки и инциденты\nОшибок нет.",  # noqa: RUF001
        }


def test_full_report_payload_loads_audit_and_returns_chunks() -> None:
    payload = full_report_payload(
        audit_id=7, chat_id=-1001, directus=_FullReportDirectus()
    )

    assert payload["audit_id"] == 7
    assert payload["chat_id"] == -1001
    assert payload["messages"]
    assert "Ошибок нет" in payload["messages"][0]


class _CooldownDirectus:
    url = "https://jcall.io/directus"

    def __init__(self) -> None:
        self.ensure_called = False

    def list_incidents_for_call(self, call: CallContext) -> list[dict]:
        return []

    def list_rules(self) -> list[DiagnosticRule]:
        return [
            DiagnosticRule(
                id=11,
                enabled=True,
                target="both",
                trigger_mode="all_calls",
                cooldown_sec=60,
            )
        ]

    def find_audit_by_dedupe_key(self, dedupe_key: str) -> dict | None:
        return None

    def find_recent_audit_for_rule(
        self, *, call: CallContext, rule: DiagnosticRule
    ) -> dict | None:
        return {"id": 21, "status": "completed"}

    def ensure_audit(
        self,
        *,
        call: CallContext,
        rule: DiagnosticRule,
        incidents: list[dict],
    ) -> tuple[int, bool]:
        self.ensure_called = True
        raise AssertionError("cooldown should skip before creating an audit")


class _NoRunRunner:
    repo_dir = Path("/repo")


def test_run_diagnostics_skips_with_rule_cooldown() -> None:
    directus = _CooldownDirectus()

    result = run_diagnostics(
        _call().payload,
        target="cloud",
        directus=directus,
        runner=_NoRunRunner(),
    )

    assert result["trigger"] == "aftercall"
    assert result["audits"] == [
        {
            "audit_id": 21,
            "status": "skipped",
            "reason": "cooldown",
            "cooldown_sec": 60,
        }
    ]
    assert not directus.ensure_called


class _ConflictDirectus(DirectusClient):
    def __init__(self) -> None:
        self.lookup_count = 0

    def _request(self, method: str, path: str, **kwargs):
        if method == "GET" and path == "/items/robot_call_audits":
            self.lookup_count += 1
            if self.lookup_count == 1:
                return []
            return [{"id": 31, "status": "queued", "verdict": None}]
        if method == "POST" and path == "/items/robot_call_audits":
            request = httpx.Request("POST", "https://jcall.io/directus")
            response = httpx.Response(409, request=request)
            raise httpx.HTTPStatusError(
                "duplicate dedupe key", request=request, response=response
            )
        raise AssertionError(f"unexpected request: {method} {path}")


def test_ensure_audit_handles_unique_dedupe_race() -> None:
    client = _ConflictDirectus()
    rule = DiagnosticRule(id=42, enabled=True, target="both", trigger_mode="all_calls")

    audit_id, created = client.ensure_audit(call=_call(), rule=rule, incidents=[])

    assert audit_id == 31
    assert created is False
