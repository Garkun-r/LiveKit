# Robot Diagnostics

Документ описывает диагностический блок LiveKit-робота: единый журнал
инцидентов, формат записи и правила подключения новых модулей/плагинов.

## Зачем Это Нужно

LiveKit Agent Insights и логи полезны для разбора конкретной сессии, но
они не являются единым operational-журналом для бизнеса. Нам нужен свой
журнал, который:

- сохраняется на VPS в Postgres, рядом с Directus;
- виден в Directus как обычная таблица;
- собирает объективные ошибки и нестандартные ситуации во время звонка;
- не меняет voice flow, провайдеров, prompts, fallback, таймауты или поведение
  клиента;
- позже станет источником для Telegram-уведомлений.

В этом MVP логируются только события внутри LiveKit agent и смежных API.
Asterisk/dialplan и LiveKit webhook receiver для pre-agent этапов будут
отдельным этапом.

Основано на LiveKit docs:

- Agent Insights: https://docs.livekit.io/deploy/observability/insights/
- Data hooks: https://docs.livekit.io/deploy/observability/data/
- Agent events: https://docs.livekit.io/reference/agents/events/
- Directus authentication: https://directus.io/docs/api/authentication
- Directus items API: https://directus.io/docs/api/items

## Где Хранится

Основное хранилище: VPS Postgres database, который использует Directus.
Агент в production пишет не напрямую в Postgres, а через Directus API over HTTPS.
Прямой Postgres transport оставлен только как dev/fallback path.

Таблица:

```text
public.robot_incidents
```

SQL-схема лежит в:

```text
agents/main-bot/schema/robot_incidents.sql
```

Directus-метаданные, DB-grants для `directus_user` и права роли `Livekit`
лежат отдельно:

```text
agents/main-bot/schema/robot_incidents_directus.sql
```

Агент не создает таблицу сам во время звонка. Это намеренно: миграция схемы,
права ролей и Directus-настройки должны применяться отдельно и явно, чтобы не
рисковать production-базой.

## Подключение К VPS/Directus

Production transport:

```env
INCIDENT_LOG_TRANSPORT=directus
INCIDENT_DIRECTUS_URL=https://jcall.io/directus
INCIDENT_DIRECTUS_TOKEN=<service-token>
```

Агент отправляет:

```http
POST /items/robot_incidents
Authorization: Bearer <service-token>
```

Directus role/policy `Livekit` должна иметь минимум `create` на collection
`robot_incidents`. Для ручной проверки в Directus UI можно дать `read`, но
для runtime insert достаточно `create`.

На VPS это настраивается так:

```bash
sudo -u postgres psql -d voicebot -f agents/main-bot/schema/robot_incidents.sql
sudo -u postgres psql -d voicebot -f agents/main-bot/schema/robot_incidents_directus.sql
```

Если таблица была создана после старта Directus, нужен refresh схемы Directus.
В текущем VPS-стеке `POST /utils/cache/clear` не подхватил новую collection,
поэтому после первичного создания таблицы был нужен restart Directus container.
После restart API должен отвечать `200` на:

```http
GET /items/robot_incidents?limit=1&fields=id
POST /items/robot_incidents?fields=id
```

DB-user Directus должен иметь только нужный минимум для runtime:

- `USAGE` на schema `public`;
- `SELECT, INSERT` на `public.robot_incidents`;
- `USAGE, SELECT` на sequence `public.robot_incidents_id_seq`.

Прямой Postgres fallback:

```env
INCIDENT_LOG_TRANSPORT=postgres
INCIDENT_POSTGRES_DSN=postgresql://...
```

Не используйте прямой Postgres transport для LiveKit Cloud без отдельного
согласования: это требует сетевого доступа к PostgreSQL и отдельного DB-пароля.

Если отдельный обработчик Telegram позже будет менять `status`, ему понадобится
`update(status)` или отдельная роль для incident processor.

Directus должен видеть таблицу как existing collection. Бизнес-редактирование
строк из Directus лучше ограничить статусом/комментариями, а не менять исходный
payload события.

## Формат Записи

Ключевые поля:

- `created_at`: время события.
- `environment`: `cloud`, `local`, `staging` или другой label.
- `source`: кто пишет событие, например `livekit_agent`, future `webhook`,
  future `asterisk_monitor`.
- `severity`: `info`, `warning`, `error`, `critical`.
- `incident_type`: стабильный machine-readable тип.
- `status`: `open` по умолчанию.
- `caller_phone`, `did`, `trace_id`, `room_name`, `job_id`, `sip_call_id`:
  поля корреляции звонка.
- `component`: `llm`, `stt`, `tts`, `prompt_repo`, `n8n_export`,
  `plugin:<name>`.
- `provider`, `model`: внешний сервис/модель, если применимо.
- `latency_ms`: задержка, если событие связано со временем.
- `error_type`: класс или категория ошибки.
- `description`: короткое человекочитаемое описание.
- `fingerprint`: стабильный ключ группировки похожих событий.
- `payload`: sanitized JSON с деталями.

Логгер редактирует payload перед записью и пытается вырезать очевидные tokens,
api keys, authorization headers и secret-like строки. Но в payload все равно
нельзя намеренно передавать секреты.

## Что Логируется Сейчас

`prompt_lookup_failed`
: prompt lookup в Postgres упал, агент использовал file prompt.

`session_start_failed`
: агент не смог собрать pipeline или запустить `AgentSession.start`.

`agent_session_error`
: LiveKit `session.on("error")`; включает recoverable/unrecoverable ошибки STT,
LLM, TTS и session runtime.

`provider_fallback`
: LLM/STT fallback adapter переключился, manual LLM fallback сработал, или
configured STT/TTS provider не был использован на старте.

`slow_response`
: `ChatMessage.metrics.e2e_latency` превысил `INCIDENT_SLOW_RESPONSE_MS`.

`reply_watchdog_fired`
: после финального user transcript не появилась реплика агента до watchdog
таймаута, и существующий safety path был запущен.

`tool_failed`
: tool внутри агента упал. Сейчас это покрывает `end_call`; будущие tools
должны использовать тот же логгер.

`abnormal_close`
: сессия закрылась с ошибкой, cancellation, failed/timeout reason или проблема
при `delete_room`.

`n8n_export_failed`
: session export в n8n упал или превысил timeout.

Дополнительно в существующий n8n session payload добавлены
`component_metrics_events`. Это per-plugin `metrics_collected`, а не новая
логика на deprecated session-level metrics.

## Как Подключать Новые Плагины

Новый модуль не должен писать в БД напрямую. Он должен получать общий
`IncidentLogger` из agent runtime и писать через него.

Минимальный паттерн:

```python
incident_log.record_nowait(
    "geo_lookup_failed",
    severity="warning",
    component="plugin:geo_search",
    provider="2gis",
    description="Geo search API failed",
    payload={"query": query, "city": city},
)
```

Для exception:

```python
incident_log.record_exception_nowait(
    "translation_failed",
    exc,
    severity="warning",
    component="plugin:translation",
    provider="deepl",
    description="Translation plugin request failed",
    payload={"target_language": "ru"},
)
```

Для куска кода, где ошибку нужно залогировать и пробросить дальше:

```python
async with incident_log.observe(
    "plugin_failed",
    component="plugin:crm_lookup",
    provider="directus",
    description="CRM lookup failed",
):
    await lookup_customer()
```

Правила для будущих `incident_type`:

- использовать stable snake_case name;
- не включать phone/room/provider в `incident_type`;
- детали класть в `payload`;
- для внешних API всегда указывать `component`, `provider`, `model` если есть;
- не логировать секреты и полные request headers.

## Error Classification

Логгер классифицирует provider/API ошибки в `payload.error_category`:

- `auth_or_key`: invalid key, unauthorized, forbidden.
- `quota_or_billing`: billing, balance, credits, quota exceeded.
- `rate_limit`: 429 или rate limit.
- `timeout`: timeout/timed out.
- `network`: connection, DNS, socket, websocket, SSL.
- `provider_5xx`: HTTP 5xx.
- `unknown`: все остальное.

Эта классификация нужна для Telegram routing позже: например, billing/key
ошибки должны будить владельца, а recoverable transient 5xx можно агрегировать.

## Конфигурация

```env
INCIDENT_LOG_ENABLED=true
INCIDENT_LOG_TRANSPORT=directus
INCIDENT_DIRECTUS_URL=https://jcall.io/directus
INCIDENT_DIRECTUS_TOKEN=
INCIDENT_POSTGRES_DSN=
INCIDENT_ENVIRONMENT=cloud
INCIDENT_DB_TIMEOUT_SEC=1.5
INCIDENT_SLOW_RESPONSE_MS=7000
```

`INCIDENT_DB_TIMEOUT_SEC` должен быть коротким. Если VPS/Directus/Postgres
недоступен, звонок не должен падать из-за диагностики.

## Границы MVP

Не покрыто сейчас:

- Asterisk принял звонок, но LiveKit его не увидел.
- LiveKit получил SIP participant, но agent dispatch не появился.
- Полная semantic-оценка “робот вел себя не так”.
- Проверка transfer success без явного transfer tool/dialplan marker.

Для первых двух пунктов нужен следующий этап:

- Asterisk start/end event + `X-TRACEID`/`X-DID`.
- LiveKit webhook receiver для `room_started`, `participant_joined`,
  `participant_connection_aborted`, `room_finished`.

Эти изменения требуют отдельного server/deploy approval.
