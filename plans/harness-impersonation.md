# Plan: Harness Impersonation (провайдер прикидывается кодинг-агентом)

## Goal

Дать роутеру возможность на уровне **конкретного провайдера** представляться апстриму
как известный кодинг-агент (Pi, Claude Code, Codex, Cline, Roo, Crush, …) — набором
HTTP-заголовков (и опционально телом запроса), задаваемым декларативно в YAML,
без правок кода под каждый новый агент.

## Context / why

- Часть апстримов (z.ai coding plan, OpenRouter-подобные, вендорские "coding" тарифы)
  различает клиентов по `User-Agent` / SDK-заголовкам и включает/выключает лимиты и фичи.
- Сейчас единственный механизм — статический `headers:` в `providers.yaml`
  (`base.py:98`, мержится в каждый запрос в `_make_request`, `base.py:320`).
  Он есть, но: без версионирования, без per-request полей (session id), без переиспользования
  между провайдерами, без документации, что вообще надо подделывать.
- `extra_headers` в `_make_request` уже поддерживает per-request добавку — точка расширения есть,
  ломать ничего не надо. INVARIANT: `Authorization` не перезаписывается (`base.py:322-325`) — сохраняем.

⚠️ Замечание: подмена идентичности клиента формально может нарушать ToS отдельных апстримов.
Решение — за оператором; технически всё ниже реализуемо.

## Что вообще составляет "подпись" харнесса

| Слой | Примеры | Реализуемо у нас |
|---|---|---|
| 1. UA | `claude-cli/1.0.x (external, cli)`, `codex_cli_rs/…`, `pi/…` | тривиально |
| 2. SDK-заголовки | `X-Stainless-Lang/OS/Arch/Runtime/Package-Version/Retry-Count`, `anthropic-version`, `anthropic-beta: claude-code-…`, `originator`, `session_id`, `OpenAI-Beta` | тривиально (часть — динамическая) |
| 3. Роутерные | `HTTP-Referer`, `X-Title` (уже используем для openrouter) | есть |
| 4. Тело запроса | системный промпт-преамбула («You are Claude Code…»), `metadata.user_id`, форма tool-схем, расстановка `cache_control` | возможно, но инвазивно |
| 5. Транспорт | порядок заголовков, TLS/JA3, HTTP/2 SETTINGS | **httpx не даёт**; нужен `curl_cffi`/`tls-client` |

Вывод: делаем 1–3 полноценно, 4 — опционально и выключено по умолчанию, 5 — вне scope
(зафиксировать как известное ограничение).

## Research: под кого мимикрировать (веб, авг 2026)

**Главный вывод: Pi — НЕ самый безпалевный, скорее наоборот.** В экосистеме Pi существует
пакет `@aizigao/pi-claude-code-headers-compat`, единственная задача которого — переписать
заголовки Pi под Claude Code, потому что дефолтные заголовки Pi ловят **Cloudflare 403**
(трактуются как crawler-трафик). Он выставляет:

```
user-agent: 2.1.178 (Claude Code)
anthropic-version: 2023-06-01
accept: application/json
content-type: application/json
```

и **удаляет** `x-api-key`, `anthropic-dangerous-direct-browser-access`, `accept-language`,
`x-app`, `x-pi-provider-marker`, `x-stainless-*`, `sec-fetch-*`.

То есть индустрия де-факто мимикрирует **в обратную сторону** — все под Claude Code.

### Что известно про подписи

| Агент | Подпись | Надёжность источника |
|---|---|---|
| Claude Code | UA `claude-code/<ver> (cli)` (детекторы матчат по префиксу `claude-code/`); ранее/также токен `claude-cli`; + stainless-набор `x-stainless-{lang,os,arch,runtime,runtime-version,package-version,retry-count,helper-method}`, `anthropic-version: 2023-06-01`, `anthropic-beta` (напр. `prompt-caching-scope-2026-01-05,advanced-tool-use-2025-11-20`), `anthropic-dangerous-direct-browser-access` | высокая, версии протухают |
| Pi | `x-app`, `x-pi-provider-marker`, `sec-fetch-*`, свой runtime UA; есть opt-out телеметрии (`PI_TELEMETRY=0`) | средняя |
| Codex CLI | `originator: codex_cli_rs`, UA `codex_cli_rs/<ver>` | средняя, перепроверить |
| OpenRouter-клиенты | `HTTP-Referer` + `X-Title` (это не UA-подделка, это штатная атрибуция) | точно |

### Рекомендация по выбору

1. **Claude Code — самый безопасный выбор** для апстримов за Cloudflare и для «coding plan»
   тарифов: его UA белоспискован повсеместно, а stainless-набор легко воспроизвести
   (мы шлём OpenAI-совместимые запросы, но заголовки апстримом чаще проверяются отдельно от тела).
2. **Pi** оставить как профиль, но не дефолтом — его подпись как раз ловится фильтрами.
3. `HTTP-Referer`/`X-Title` — всегда, где апстрим их понимает: это легальная атрибуция, а не подделка.

### Как получать значения (важнее, чем блог-посты)

Версии в UA протухают за недели, и по блогам их собирать бессмысленно. Правильный путь —
**снять подпись эмпирически**:

- поднять эхо-эндпоинт (`/v1/debug/echo-headers` в самом роутере, за админ-ключом),
  прописать его как base_url в настоящем Claude Code / Pi / Codex и записать реальный набор;
- либо mitmproxy на localhost для того же;
- сложить снятое в `config/harness_profiles.yaml` и версионировать в git.

Это же даёт регресс-проверку: если апстрим начнёт отбивать — сравнить свежий дамп с профилем.

### Риски

- Версия в UA стареет → профиль надо обновлять руками (сознательно не автоматизируем).
- Проверка тела запроса (system-преамбула Claude Code) — если апстрим до неё дойдёт,
  заголовков не хватит; см. «слой тела», п. 4 Design.
- Порядок заголовков / TLS-отпечаток httpx ≠ Node/Bun-отпечаток настоящего Claude Code.
  Cloudflare это умеет, но на практике UA-фильтра хватает; полный фикс — вне scope.

## Research 2: Kilo Code / OpenCode — проверено по исходникам (авг 2026)

Оба открытые, оба официально числятся поддерживаемыми клиентами GLM Coding Plan
(«works with 20+ clients… Claude Code, Kilo Code, Cline, OpenCode»). Значит представляться
ими — это **штатная атрибуция клиента**, а не обход: мы шлём ровно те же заголовки,
что шлёт легальный клиент того же тарифа. Никакого «мы — Claude Code» и никакого обхода Cloudflare.

### OpenCode (`sst/opencode`, `packages/opencode/src/provider/provider.ts`)

Для OpenAI-совместимых / OpenRouter-подобных апстримов **весь набор — два заголовка**:

```
HTTP-Referer: https://opencode.ai/
X-Title: opencode
```

Вариации per-provider: `llmgateway` +`X-Source: opencode`; `nvidia` +`X-BILLING-INVOKE-ORIGIN: OpenCode`;
`cerebras` — `X-Cerebras-3rd-Party-Integration: opencode`; `vercel` — те же два в нижнем регистре.

`User-Agent` **не переопределяется** — уходит UA рантайма (Bun). Явный UA есть только на
gitlab/cloudflare-путях: `opencode/<version> cloudflare-ai-gateway (<platform> <release>; <arch>)`.

На anthropic-пути OpenCode шлёт
`anthropic-beta: interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14` —
нам не нужно, мы OpenAI-совместимые.

### Kilo Code (`Kilo-Org/kilocode`, актуальный релиз **v7.5.5**)

Kilo с 7.x — **форк OpenCode** (в репо лежит `packages/opencode/`), заголовки живут в
`packages/kilo-gateway/src/{headers.ts,api/constants.ts}`:

```
User-Agent: opencode-kilo-provider[/<KILOCODE_VERSION>]     # USER_AGENT_BASE = "opencode-kilo-provider"
Content-Type: application/json
X-KILOCODE-EDITORNAME: "Kilo CLI[ <version>]"               # или KILOCODE_EDITOR_NAME вербатим,
                                                            # напр. "Visual Studio Code 1.114.0"
```

Условные (только при наличии данных): `X-KILOCODE-TASKID`, `X-KILOCODE-PARENT-TASKID`,
`X-KILOCODE-ORGANIZATIONID`, `X-KILOCODE-PROJECTID`, `X-KILOCODE-MACHINEID`,
`X-KILOCODE-FEATURE` (env `KILOCODE_FEATURE`), `X-KILOCODE-TESTER: SUPPRESS`.
Кросс-клиентская атрибуция в старых/расширенческих сборках: `http-referer: https://kilocode.ai`,
`x-title: Kilo Code`, `x-kilocode-version: <ver>`.

Нюанс форка: UA у Kilo базово `opencode-kilo-provider`, то есть апстрим, фильтрующий по
подстроке `opencode`, пропустит оба. Версия в UA берётся из env `KILOCODE_VERSION` — если
её не выставить, UA вообще без версии (`opencode-kilo-provider`), что удобно: **нечему протухать**.

### Итог для нас

| Профиль | Заголовки | Риск |
|---|---|---|
| `opencode` **(дефолт)** | `HTTP-Referer: https://opencode.ai/`, `X-Title: opencode` | ~ноль: штатная атрибуция |
| `kilocode` | `User-Agent: opencode-kilo-provider` (можно без версии), `X-KILOCODE-EDITORNAME: Kilo CLI`, +`http-referer`/`x-title` | ~ноль, но больше полей → больше шансов на несостыковку |
| `claude-code` | UA `claude-code/<ver> (cli)` + stainless-набор | серая зона, опция, не дефолт |

**Практическое следствие: профиль `opencode` — это две строчки в существующем `headers:`
в `providers.yaml`, работает уже сегодня без единой строки кода.**
Реестр профилей (вариант B) нужен, чтобы не копипастить их по всем провайдерам и чтобы
`kilocode`/`claude-code` с динамическими полями не хардкодить.

Порядок: сначала руками прописать `opencode`-пару в нужные провайдеры и проверить, что
апстрим доволен. Если да — реестр можно не делать вовсе либо делать только ради
`{uuid4}`-полей Kilo (`X-KILOCODE-TASKID` / `MACHINEID`).

## Варианты

**A. Ничего не делать, писать `headers:` руками.**
0 кода. Минусы: копипаста между провайдерами, нет динамических полей, нет ни одного
задокументированного профиля — оператор сам должен знать, что подделывать. Не масштабируется.

**B. (рекомендуется) Реестр профилей + ссылка из провайдера.**
Новый `config/harness_profiles.yaml` c именованными профилями; в `providers.yaml` —
ключ `harness: pi`. Профиль разворачивается в заголовки при инстанцировании провайдера,
явный `headers:` провайдера имеет приоритет. Плюс поддержка динамических плейсхолдеров
(`{uuid}`, `{session_id}`, `{os}`, `{arch}`) для per-request полей.

**C. Полная импersonation, включая тело и TLS.**
Профиль дополнительно инжектит system-преамбулу и `metadata`, транспорт — на `curl_cffi`
ради JA3. Дорого, ломает «thin gateway», тянет новый HTTP-стек и убивает существующий
пул/прокси/стриминг. **Нет.**

**D. Pass-through реального клиента.**
Пробрасывать наверх `User-Agent` и белый список заголовков *настоящего* клиента роутера.
Честно и бесплатно, но работает только если клиент и правда Claude Code/Pi. Полезно как
режим `harness: passthrough` — добавляем как частный случай B, не как альтернативу.

**Решение: B, с `passthrough` как одним из режимов. Дефолт — профиль `opencode`
(легальная атрибуция, две строчки, нулевой ToS-риск). `claude-code` — опция, если апстрим
требует именно его; `pi` дефолтом не делать (его подпись как раз ловится Cloudflare).**

## Design (вариант B)

### 1. `config/harness_profiles.yaml` (новый, hot-reload как остальные)

```yaml
profiles:
  opencode:                      # рекомендуемый дефолт
    headers:
      HTTP-Referer: "https://opencode.ai/"
      X-Title: "opencode"
  kilocode:
    headers:
      User-Agent: "opencode-kilo-provider/7.5.5"
      X-KILOCODE-EDITORNAME: "Kilo CLI 7.5.5"
      http-referer: "https://kilocode.ai"
      x-title: "Kilo Code"
    per_request:
      X-KILOCODE-TASKID: "{uuid4}"
  pi:
    headers:
      User-Agent: "pi/0.4.2 (cli; darwin arm64)"
      X-Client: "pi"
    per_request:                 # рендерится на каждый запрос
      X-Session-Id: "{uuid4}"
  claude-code:
    headers:
      User-Agent: "claude-cli/1.0.72 (external, cli)"
      X-Stainless-Lang: "js"
      X-Stainless-Package-Version: "0.60.0"
      X-Stainless-OS: "MacOS"
      X-Stainless-Arch: "arm64"
      X-App: "cli"
      anthropic-beta: "claude-code-20250219,oauth-2025-04-20"
  codex:
    headers:
      User-Agent: "codex_cli_rs/0.20.0 (Mac OS 15; arm64)"
      originator: "codex_cli_rs"
```

Плейсхолдеры: `{uuid4}`, `{ts}`, `{request_id}`. Рендер — простой `str.format_map` с
дефолтом (неизвестный плейсхолдер → оставить как есть + warning). Никаких шаблонизаторов.

### 2. `providers.yaml`

```yaml
  glm:
    type: openai
    base_url: https://api.z.ai/api/coding/paas/v4
    api_key_env: ZAI_API_KEY
    harness: pi            # | claude-code | codex | passthrough | (unset = как сейчас)
    headers:               # точечный override поверх профиля
      X-Title: "nnp.space"
```

Приоритет (низший → высший): профиль → `headers:` провайдера → `Content-Type`/`Authorization`
(последний неприкосновенен).

### 3. Код

- `src/core/harness_profiles.py` — загрузка/валидация реестра (soft-validate по образцу
  `model_info.yaml`: неизвестные ключи и ссылки на несуществующий профиль → `logger.warning`;
  ссылка на несуществующий профиль на **старте** → fail-fast, как остальная валидация провайдеров).
- `ConfigManager` — отдать `harness_profiles` в общий hot-reload цикл + очистка кеша провайдеров
  (кеш и так чистится на reload, так что профиль подхватится).
- `BaseProvider.__init__` — после `self.headers = dict(config.get("headers") or {})`
  вставить слой профиля **под** ним; сохранить `self._harness_per_request` для рендера.
- `BaseProvider._make_request` / `_stream_request` — рендерить `per_request` и класть в
  `merged_headers` до применения `extra_headers` (тот же запрет на `Authorization`).
  Сейчас `_stream_request` (`base.py:432`) шлёт голый `self.headers` — **надо унифицировать**,
  иначе стрим и не-стрим будут иметь разную подпись (это само по себе fingerprint).
- `mask_headers` — убедиться, что новые заголовки не содержат секретов; UA логировать полезно.
- `passthrough`: сервис кладёт whitelisted заголовки клиента в `extra_headers`
  (`User-Agent`, `X-Stainless-*`, `anthropic-beta`); требует прокинуть их из `chat_service`.

### 4. Опционально (флагом, по умолчанию off) — слой тела

`profile.body.system_prefix` / `body.metadata` мержится в тело запроса.
Отдельный ключ `harness_body: true` у провайдера. Делать **только** если выяснится,
что апстрим проверяет не только заголовки. Не в первой итерации.

## Тесты

- юнит: рендер профиля, приоритет `профиль < headers < Authorization`, `{uuid4}` уникален между запросами;
- юнит: несуществующий профиль → fail-fast на старте; кривой YAML → warning, не падаем;
- юнит: стрим и не-стрим шлют одинаковый набор заголовков;
- API: провайдер с `harness: pi` — заголовки долетают (мок-апстрим, эхо заголовков).

## Не делаем

- TLS/JA3 и порядок заголовков (нужен другой HTTP-стек — прощай пул, прокси, стриминг);
- ротацию версий/ОС «для правдоподобия» — константа на профиль, меняется правкой YAML;
- автообновление подписей реальных агентов из внешних источников.

## Порядок работ

1. `harness_profiles.py` + `config/harness_profiles.yaml` (профили `pi`, `claude-code`, `codex`).
2. Слой профиля в `BaseProvider.__init__` + унификация заголовков стрима.
3. `per_request` плейсхолдеры.
4. Тесты + README (раздел про `harness:`).
5. `passthrough` — отдельным шагом, после 1–4.
