# LiveKit

Монорепозиторий для LiveKit-агентов.

Структура:
- agents/ — отдельные агенты
- shared/ — общие модули, веб-хуки, утилиты, промпты
- docs/ — документация
- .agents/ — инструкции и skills для AI

Первый агент:
- agents/main-bot

Операционные runbook:
- [Слепок текущей системы](./docs/current-livekit-system-snapshot.md)
- [Профили деплоя и env](./docs/deployment-profiles.md)
- [Локальный LiveKit на Asterisk-сервере](./docs/local-livekit-server.md)
- [LiveKit Cloud](./docs/cloud/README.md)
- [Asterisk E2E Voice Test](./docs/asterisk-e2e-voice-test.md)
- [Directus-настройки робота](./docs/robot-settings-directus.md)
- [Directus prompt cache](./docs/directus-prompt-cache.md)
- [Voice fallback architecture](./docs/voice-fallback-architecture.md)
- [Парсер тегов и навыки робота](./docs/robot-tags-and-skills.md)
- [Диагностика и журнал инцидентов робота](./docs/robot-diagnostics.md)
- [Post-call Codex диагностика звонков](./docs/codex-call-diagnostics.md)
