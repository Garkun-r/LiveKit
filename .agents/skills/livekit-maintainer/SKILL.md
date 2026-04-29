---
name: livekit-maintainer
description: Support and modify LiveKit voice agents, webhooks, DB calls, and deployment files safely.
---

# LiveKit Maintainer Skill

Используй этот навык, когда нужно:
- дописать webhook
- изменить настройки агента
- добавить обращение к БД
- подключить внешний API
- не сломать текущий voice flow

Правила:
- сначала найди точку входа агента
- отдельно проверь env-переменные
- не вставляй секреты в код
- сохраняй текущий voice flow, провайдеров, модели и промпты по умолчанию
- не меняй LLM/STT/TTS provider, модель, fallback, timeout/retry policy, handoff/workflow или prompt без явного согласования владельца
- если провайдер медленный или падает, сначала ищи корневую причину; замену провайдера предлагай как бизнес-решение с tradeoff по качеству, задержке, стоимости и rollback
- общую логику выноси в shared/
- перед деплоем проверяй зависимости и структуру
