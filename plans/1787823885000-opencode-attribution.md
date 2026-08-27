# Plan: атрибуция как OpenCode (полный набор заголовков)

Узкий план. Большой разбор всех харнессов — в [harness-impersonation.md](harness-impersonation.md).

## Goal

Исходящие запросы к внешним апстримам неотличимы от запросов клиента **OpenCode** на
уровне HTTP-заголовков. Цель — ходить в coding-plan тарифы через один роутер, оставаясь
официально поддерживаемым клиентом.

## Почему это не подделка

OpenCode открыт и числится в списке поддерживаемых клиентов GLM Coding Plan. Мы шлём то же,
что шлёт легальный клиент того же тарифа.

## Что реально шлёт OpenCode (проверено по `sst/opencode@dev`, релиз v1.18.23)

### Точка правды: `packages/opencode/src/session/llm/request.ts`

```ts
const USER_AGENT = `opencode/${InstallationVersion}`        // :18

headers: {
  ...(providerID.startsWith("opencode")
    ? { "x-opencode-project": …, "x-opencode-session": …,
        "x-opencode-request": …, "x-opencode-client": …,
        "User-Agent": USER_AGENT }
    : { "x-session-affinity": sessionID,                     // :197
        "X-Session-Id": sessionID,                           // :198
        "User-Agent": USER_AGENT }),                          // :199
  ...(parentSessionID ? { "x-parent-session-id": parentSessionID } : {}),
  ...model.headers,
  ...headers,                                                // provider-level
}
```

**Поправка к прошлому выводу: `User-Agent` OpenCode ставит на КАЖДОМ LLM-запросе.**
Раньше я смотрел только `provider.ts` (там UA только на gitlab/cloudflare-путях) и сделал
неверный вывод. Реальный набор шире.

### Итоговый набор для стороннего (не `opencode/*`) провайдера

```
User-Agent: opencode/1.18.23
x-session-affinity: ses_<26 симв.>
X-Session-Id: ses_<26 симв.>
Content-Type: application/json
Authorization: Bearer <key>
```

Плюс **только если у провайдера есть кастомный лоадер** в `provider.ts`:

| Провайдер | Доп. заголовки |
|---|---|
| openrouter, vercel, google-vertex, kilo | `HTTP-Referer: https://opencode.ai/`, `X-Title: opencode` |
| llmgateway | те же + `X-Source: opencode` |
| nvidia | те же + `X-BILLING-INVOKE-ORIGIN: OpenCode` |
| cerebras | только `X-Cerebras-3rd-Party-Integration: opencode` |
| anthropic | `anthropic-beta: interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14` |

### ⚠️ Два подводных камня

1. **`HTTP-Referer`/`X-Title` — НЕ универсальны.** Для z.ai/GLM и любого «просто
   OpenAI-совместимого» провайдера в `provider.ts` кастомного лоадера **нет** → настоящий
   OpenCode туда referer/title **не шлёт**. Отправить их — это ровно та деталь, по которой
   нас отличат. Шлём их только тем апстримам, что в таблице выше (у нас — `openrouter`).
2. **`x-opencode-*` слать нельзя.** Они уходят только на собственный бэкенд OpenCode
   (`opencode zen`). На стороннем апстриме это мгновенный маркер подделки.

### Формат session id

`ses_` + 26 символов (`packages/core/src/id/id.ts`, `packages/schema/src/identifier.ts`):
12 hex-символов из `BigInt(Date.now()) * 0x1000 + counter` (при `descending` — побитово
инвертировано) + 14 символов из алфавита `0-9A-Za-z`.

**Ключевая поведенческая деталь: session id стабилен в пределах сессии, а не случаен на
каждый запрос.** `x-session-affinity` буквально существует ради sticky-routing. Новый
рандом на каждый запрос — заметная аномалия, из-за которой и можно словить бан. Направление
(ascending/descending) я по исходникам не подтвердил — на форму (26 символов) это не влияет.

## Что делаем

### 1. Профиль `opencode` — уже не сводится к конфигу

Из-за session id нужен код: генератор id + его стабильное хранение. Реализуем минимально,
не тащя весь реестр профилей из большого плана.

### 2. `src/core/opencode_identity.py` (новый, ~60 строк)

- `new_session_id() -> str` — порт `create()` из `identifier.ts` (12 hex + 14 base62).
- `SessionRegistry` — `dict[key] -> (session_id, last_seen)`, TTL из env
  (`OPENCODE_SESSION_TTL`, дефолт 3600с), фоновая очистка не нужна — ленивое вытеснение.
- Ключ сессии: `project_name` из `RequestContext` (+ имя провайдера). Один клиентский
  проект = одна upstream-сессия, пока он активен. Это самое близкое к реальности,
  что у нас есть, и оно стабильно.

### 3. `providers.yaml` — новый ключ

```yaml
  glm:
    type: openai
    base_url: https://api.z.ai/api/coding/paas/v4
    api_key_env: ZAI_API_KEY
    identity: opencode          # unset = текущее поведение
    identity_version: "1.18.23" # версия в UA, обновляется руками
```

`headers:` остаётся как есть и имеет приоритет над профилем (для `openrouter` —
там свои referer/title).

### 4. `src/providers/base.py`

- В `__init__`: при `identity: opencode` положить `User-Agent: opencode/<identity_version>`
  в `self.headers`; сохранить флаг.
- Session-заголовки — **per-request** (`x-session-affinity`, `X-Session-Id`), значит идут
  через `extra_headers`. Сервис прокидывает `RequestContext` → провайдер берёт session id
  из реестра.
- **Обязательно починить стрим:** `_stream_request` шлёт голый `self.headers`
  ([base.py:432](../src/providers/base.py#L432)) и игнорирует `extra_headers`, тогда как
  `_make_request` их мержит ([base.py:320](../src/providers/base.py#L320)). Иначе стрим
  уйдёт без session-заголовков, а не-стрим с ними — **это сам по себе fingerprint,
  и именно он нас спалит.** Вынести merge в общий хелпер, использовать в обоих путях.
  Запрет на перезапись `Authorization` сохранить.

### 5. Убрать лишнее

Проверить, что мы не шлём наверх ничего своего: `X-Request-ID`, кастомные `X-NNP-*`,
`HTTP-Referer: https://nnp.space` на провайдерах с `identity: opencode`.
Любой наш заголовок, которого нет у OpenCode, — дырка в маскировке.

## Остаточные риски (честно)

- **TLS/JA3 и порядок заголовков.** Настоящий OpenCode — Bun; мы — httpx/Python. На уровне
  отпечатка соединения мы отличимы всегда. Не чиним (нужен другой HTTP-стек, потеряем
  пул/прокси/стриминг). На практике апстримы такое почти не проверяют, но гарантий нет.
- **Тело запроса.** Системный промпт, набор tool-схем, форма `reasoning`/`cache_control`
  у нас свои. Если апстрим смотрит туда — заголовки не спасут.
- **Версия в UA протухает.** `identity_version` правится руками; следить за релизами
  `sst/opencode`.
- Поведение: реальный OpenCode на одну сессию шлёт много запросов подряд с растущим
  контекстом. Наш трафик по форме другой. Это не лечится заголовками.

## Проверка

1. DEBUG-логи `_log_provider_data` (`data_flow: to_provider`): один и тот же набор
   заголовков на stream и non-stream запросе.
2. Два запроса подряд от одного проекта → **одинаковый** `X-Session-Id`;
   от разных проектов → разные.
3. `X-Session-Id` матчится по `^ses_[0-9A-Za-z]{26}$`.
4. Никаких `x-opencode-*` и `X-NNP-*` в исходящем наборе.
5. Полный прогон существующих тестов.

## Откат

`identity:` убрать из `providers.yaml` → hot-reload за ≤5с. Фикс `_stream_request`
оставить в любом случае — это самостоятельный баг.

---

## Решение: E + C

Выбран гибрид (утверждено оператором).

**E — passthrough (база, делаем первым).**
Если клиент роутера сам харнесс — пробрасываем его настоящие заголовки наверх, ничего не
фабрикуя. Белый список: `User-Agent`, `X-Session-Id`, `x-session-affinity`,
`x-parent-session-id`, `anthropic-beta`, `x-stainless-*`. Всё остальное режем.
Включается ключом `identity: passthrough` у провайдера. Требует прокинуть заголовки
клиентского запроса из сервиса в `extra_headers`.

**C — синтетический профиль `opencode` (fallback).**
Работает, когда passthrough нечего пробрасывать (клиент не харнесс). Реализация — разделы
2–5 выше: генератор `ses_*`, реестр сессий по `project_name`, `User-Agent: opencode/<ver>`.
Приоритет: реальные заголовки клиента > синтетический профиль.

**Фикс `_stream_request` — предусловие для обоих**, делается первым коммитом отдельно.

### Порядок

1. Фикс merge заголовков в `_stream_request` + тест (стрим и non-stream дают одинаковый набор).
2. `identity: passthrough` — белый список, прокидка из сервиса, тесты.
3. `src/core/opencode_identity.py` — генератор id + реестр сессий, юнит-тесты.
4. `identity: opencode` — сборка профиля, приоритет над ним у `headers:` и у passthrough-заголовков.
5. Чистка: убедиться, что свои `X-NNP-*` / `X-Request-ID` не утекают наверх.
6. README: раздел про `identity:`.
