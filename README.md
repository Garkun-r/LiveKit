# LiveKit

Монорепозиторий для LiveKit-агентов.

Структура:
- agents/ — отдельные агенты
- shared/ — общие модули, веб-хуки, утилиты, промпты
- docs/ — документация
- .agents/ — инструкции и skills для AI

Правило бизнес-логики:
- агент может диагностировать проблемы и предлагать варианты, но не должен сам менять LLM/STT/TTS provider, модели, промпты, fallback, handoff/workflow, latency guards, turn logic или клиентское поведение;
- если текущий провайдер медленный или падает, сначала искать корневую причину;
- смена провайдера, модели, подрядчика, voice path или fallback — только после явного согласования владельца с учетом качества, задержки, стоимости, надежности и rollback.

Первый агент:
- agents/main-bot

Операционные runbook:
- [Локальный LiveKit на Asterisk-сервере](./docs/local-livekit-server.md)
- [LiveKit Cloud](./docs/cloud/README.md)
- [Asterisk E2E Voice Test](./docs/asterisk-e2e-voice-test.md)
