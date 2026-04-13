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
- общую логику выноси в shared/
- перед деплоем проверяй зависимости и структуру
