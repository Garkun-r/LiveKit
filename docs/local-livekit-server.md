# Local LiveKit Server Runbook

Актуально на 2026-04-28. Этот документ описывает локальный LiveKit-контур на
Asterisk-сервере и egress через VPS Squid HTTP CONNECT proxy.

## Hosts

- Asterisk + local LiveKit: `87.226.145.66`, SSH `root@87.226.145.66 -p 39001`.
- VPS egress proxy: `66.248.207.203`, SSH `root@66.248.207.203 -p 22222`.

Не хранить реальные ключи, токены, SIP-пароли и содержимое `.env` в git. В
репозитории допустимы только `.env.example` и sanitized-документация.

## Active Services

На Asterisk/local LiveKit сервере:

```console
jcall-livekit-agent.service
livekit-local.service
livekit-sip-local.service
jcall-egress-ssh-tunnel.service
```

Ожидаемые локальные listeners:

```console
127.0.0.1:7880   # livekit-server
127.0.0.1:18081  # main-bot AgentServer
127.0.0.1:15001  # legacy SSH tunnel to old VPS proxy, kept for rollback
```

На VPS:

```console
jcall-squid-egress.service
jcall-egress-proxy.service  # legacy Python CONNECT proxy on 127.0.0.1:15081
ssh
nginx
docker
```

Ожидаемые VPS listeners:

```console
0.0.0.0:15182    # Squid HTTP CONNECT, primary egress proxy
127.0.0.1:15081  # legacy Python proxy, rollback only
0.0.0.0:443      # nginx
```

## File Locations

На Asterisk/local LiveKit сервере:

```console
/opt/jcall-livekit-agent/main-bot        # deployed agent working tree
/etc/jcall-livekit-agent/main-bot.env    # production env, do not commit
/etc/systemd/system/jcall-livekit-agent.service
/etc/systemd/system/livekit-local.service
/etc/systemd/system/livekit-sip-local.service
/etc/systemd/system/jcall-egress-ssh-tunnel.service
/etc/livekit-local/livekit.yaml
/etc/livekit-local/sip.yaml
```

На VPS:

```console
/etc/jcall-squid-egress/squid.conf
/etc/systemd/system/jcall-squid-egress.service
/var/log/squid/jcall-egress-access.log
```

В macOS/source workspace новые proxy-related файлы лежат здесь:

```console
agents/main-bot/src/egress.py
agents/main-bot/src/agent.py
agents/main-bot/src/eleven_v3_tts.py
agents/main-bot/src/cosyvoice_tts.py
agents/main-bot/src/vertex_gemini_tts.py
agents/main-bot/tests/test_egress.py
agents/main-bot/tests/test_gemini_llm_config.py
agents/main-bot/.env.example
agents/main-bot/README.md
```

## Egress Policy

Главное правило: `jcall-livekit-agent.service` не должен использовать глобальные
`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` или `AGENT_EXTERNAL_HTTP_PROXY`.
Маршрут выбирается на уровне провайдера через `src/egress.py`.

Production env должен содержать:

```console
EGRESS_PROXY_URL=http://66.248.207.203:15182
EGRESS_DEFAULT=direct
ELEVENLABS_EGRESS=proxy
GEMINI_EGRESS=proxy
GOOGLE_TTS_EGRESS=proxy
VERTEX_TTS_EGRESS=proxy
GOOGLE_STT_EGRESS=proxy
XAI_EGRESS=proxy
DEEPGRAM_EGRESS=direct
MINIMAX_TTS_EGRESS=direct
COSYVOICE_TTS_EGRESS=direct
LIVEKIT_INFERENCE_EGRESS=proxy
```

Текущий выбор основан на тестах задержки и geoblock:

- `proxy`: ElevenLabs, Gemini/Google LLM, xAI, Google TTS/STT, Vertex TTS, LiveKit Inference.
- `direct`: Deepgram, MiniMax, CosyVoice.

Squid принимает только Asterisk-сервер `87.226.145.66/32`, только метод
`CONNECT`, только порт `443`. Это основной proxy для локального робота. Legacy
SSH tunnel на `127.0.0.1:15001` сохранен только как rollback и не должен быть
основным маршрутом.

Для снижения задержки на STT final-флаге можно включить универсальный wrapper,
который берет локальный LiveKit/Silero VAD `speaking -> listening` как момент
окончания речи. Если provider final transcript не пришел за ограниченное время,
wrapper коммитит последний interim как synthetic final:

```console
STT_EARLY_INTERIM_FINAL_ENABLED=true
STT_EARLY_INTERIM_FINAL_DELAY_SEC=0.15
STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS=1
```

Wrapper не привязан к Deepgram: он ставится поверх итогового STT provider или
`FallbackAdapter`, но включается только для streaming STT с interim results и
`TURN_DETECTION_MODE=vad`. Для Deepgram безопаснее начинать с
`STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS=2`, чтобы не коммитить первый
нестабильный interim как final. После включения проверяйте
`transcription_delay`, `end_of_turn_delay` и отсутствие дублей пользовательских
сообщений в n8n payload.

## Check Current State

Asterisk/local LiveKit:

```console
ssh -p 39001 root@87.226.145.66 'systemctl is-active jcall-livekit-agent.service livekit-local.service livekit-sip-local.service jcall-egress-ssh-tunnel.service'
ssh -p 39001 root@87.226.145.66 'ss -ltnp | grep -E ":(7880|18081|15001)" || true'
ssh -p 39001 root@87.226.145.66 'asterisk -rx "core show channels" | tail -5'
```

VPS Squid:

```console
ssh -p 22222 root@66.248.207.203 'systemctl is-active jcall-squid-egress.service jcall-egress-proxy.service ssh nginx docker'
ssh -p 22222 root@66.248.207.203 'ss -ltnp | grep -E ":(15182|15081|443)" || true'
ssh -p 22222 root@66.248.207.203 'tail -n 50 /var/log/squid/jcall-egress-access.log'
```

Sanitized env route check:

```console
ssh -p 39001 root@87.226.145.66 'python3 - <<'"'"'PY'"'"'
from pathlib import Path
keys = [
    "EGRESS_PROXY_URL", "EGRESS_DEFAULT", "ELEVENLABS_EGRESS", "GEMINI_EGRESS",
    "GOOGLE_TTS_EGRESS", "VERTEX_TTS_EGRESS", "GOOGLE_STT_EGRESS", "XAI_EGRESS",
    "DEEPGRAM_EGRESS", "MINIMAX_TTS_EGRESS", "COSYVOICE_TTS_EGRESS",
    "LIVEKIT_INFERENCE_EGRESS", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
    "AGENT_EXTERNAL_HTTP_PROXY",
]
values = {}
for line in Path("/etc/jcall-livekit-agent/main-bot.env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key in keys:
        values[key] = value
for key in keys:
    print(f"{key}={values.get(key, 'UNSET')}")
PY'
```

## Deploy Agent Code

Before deploy from macOS:

```console
cd /Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot
uv run ruff check src/agent.py src/egress.py src/eleven_v3_tts.py src/cosyvoice_tts.py src/vertex_gemini_tts.py tests/test_egress.py tests/test_gemini_llm_config.py
uv run python -m pytest tests/test_egress.py tests/test_gemini_llm_config.py tests/test_xai_llm_config.py tests/test_eleven_v3_tts.py
```

Copy only changed agent files to the deployed working tree. Example:

```console
scp -P 39001 src/agent.py src/egress.py src/eleven_v3_tts.py src/cosyvoice_tts.py src/vertex_gemini_tts.py root@87.226.145.66:/opt/jcall-livekit-agent/main-bot/src/
```

Validate syntax on the server:

```console
ssh -p 39001 root@87.226.145.66 'cd /opt/jcall-livekit-agent/main-bot && sudo -u jcall-livekit-agent /usr/local/bin/uv run python -m py_compile src/agent.py src/egress.py src/eleven_v3_tts.py src/cosyvoice_tts.py src/vertex_gemini_tts.py'
```

Restart only the agent after code/env changes:

```console
ssh -p 39001 root@87.226.145.66 'systemctl restart jcall-livekit-agent.service && sleep 5 && systemctl is-active jcall-livekit-agent.service'
```

Do not restart Asterisk or change SIP/PJSIP/dialplan configs unless that is the
explicit task.

## Latency Smoke Tests

Verify Gemini uses Squid:

```console
ssh -p 39001 root@87.226.145.66 'cd /opt/jcall-livekit-agent/main-bot && sudo -u jcall-livekit-agent env HOME=/home/jcall-livekit-agent UV_CACHE_DIR=/tmp/uv-cache-jcall /usr/local/bin/uv run python - <<'"'"'PY'"'"'
from dotenv import load_dotenv
load_dotenv("/etc/jcall-livekit-agent/main-bot.env", override=True)

import asyncio
import time
from agent import build_google_llm
from egress import provider_egress

async def main() -> None:
    llm = build_google_llm()
    api = llm._client._api_client
    proxy = api._http_options.client_args.get("proxy")
    print(f"gemini_egress={provider_egress('gemini')} client_proxy={proxy}", flush=True)
    started = time.perf_counter()
    model = await llm._client.aio.models.get(model=llm.model)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"gemini_models_get=ok elapsed_ms={elapsed_ms:.1f} model={getattr(model, 'name', '')}", flush=True)

asyncio.run(main())
PY'
```

Then check Squid:

```console
ssh -p 22222 root@66.248.207.203 'tail -n 30 /var/log/squid/jcall-egress-access.log | egrep "generativelanguage|api.elevenlabs|agent-gateway"'
```

Expected: `CONNECT generativelanguage.googleapis.com:443` appears for Gemini,
and `CONNECT api.elevenlabs.io:443` appears for ElevenLabs.

Run a local Asterisk audio E2E smoke test only when there are no active calls:

```console
cd /Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot
ASTERISK_CONTEXT=lk-local-start \
ASTERISK_EXTENSION=312389 \
ASTERISK_AFTER_ANSWER_CONTEXT=lk-local-after-answer \
WAIT_AFTER_ORIGINATE_SEC=70 \
scripts/run_asterisk_audio_e2e_test.sh --run
```

The script refuses to run if Asterisk has active calls unless explicitly forced.

## Adding A Provider

New provider work should use the existing egress abstraction:

1. Choose a stable provider key, for example `openai` or `cartesia`.
2. Add `<PROVIDER>_EGRESS=direct|proxy` to `.env.example` and production env.
3. Wire the SDK through one helper from `src/egress.py`:
   - `provider_proxy_url()` for SDKs that accept an HTTP proxy URL.
   - `httpx_client_args()` for httpx/Google GenAI clients.
   - `create_external_aiohttp_session()` for aiohttp-based clients.
   - `provider_egress_env()` only for SDKs that read proxy env during construction.
4. Ensure direct providers ignore global proxy env (`trust_env=False` or equivalent).
5. Test direct and proxy routes from the Asterisk host under 10 concurrent calls.
6. Record the selected default in `src/egress.py`, `.env.example`, and this runbook.
