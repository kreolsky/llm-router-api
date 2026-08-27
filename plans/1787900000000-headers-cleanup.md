# План: чистка заголовков — удаление whitelist/opencode + пункты 1–5

Решение: остаётся **один** режим — `identity: passthrough`, который форвардит
клиентские заголовки апстриму. Whitelist (`DEFAULT_PASSTHROUGH_HEADERS`,
`passthrough_headers:`) и профиль `opencode` (синтетические сессии) удаляются.

Это снимает исходные пункты **4** (мёртвое поле в `PassthroughSpec`) и **5**
(`identity_version`) целиком — соответствующий код перестаёт существовать.
Пункт **1** теряет мотив «ключ реестра сессий», но остаётся ради логов и ошибок.

## Шаг 0 — удаление (делать первым, дальше правится меньше кода)

Удалить файлы:
- `src/core/identity_headers.py`
- `src/core/opencode_identity.py`
- `tests/unit/test_identity_headers.py`
- `tests/unit/test_opencode_identity.py`

`src/providers/base.py`:
- убрать импорт `compile_passthrough_spec`, поля `identity_version`,
  `passthrough_spec`, ветку `if self.identity == "opencode"` и валидацию
  `passthrough_headers`;
- допустимые значения `identity` → `(None, "passthrough")`, текст ошибки поправить;
- переписать ARCH-комментарий (строки ~107–113) под один режим.

`src/services/base.py`:
- `_extract_passthrough_headers(request)` — без параметра `spec`, возвращает все
  клиентские заголовки минус denylist (см. шаг 3);
- `_build_identity_headers` — убрать ветку `opencode`, `registry_key`,
  импорты `opencode_session_headers` / `identity_headers`.

`src/core/config_manager.py:187` — убрать `opencode_session_ttl` / `OPENCODE_SESSION_TTL`
из `_ENV_SETTINGS`.

Конфиг и доки:
- `config/providers.yaml` — убрать закомментированные `identity_version` и
  `passthrough_headers` (строки 7–12), оставить `identity: passthrough`;
- `CLAUDE.md` — переписать раздел **Upstream Identity**; из **Process Model**
  убрать `SessionRegistry` как process-local singleton (остаются
  `CapabilitiesCache` и SQLite writer — обоснование одного воркера сохраняется);
  убрать `OPENCODE_SESSION_TTL` из списка env;
- `.env` / `docker-compose.yml` — снять `OPENCODE_SESSION_TTL`, если есть.

Тесты: в `tests/unit/test_base_provider.py` удалить класс с тестами
`identity_*` / `passthrough_headers_*` (~строки 878–945), оставив
`test_identity_passthrough_sets_no_user_agent`, `test_unknown_identity_fails_fast`
(с новым текстом) и `test_no_identity_keeps_current_behavior`.
В `tests/unit/test_base_service.py` переписать блок с ~263 под новую сигнатуру.

## Шаг 1 — настоящее имя провайдера (исходный п.1)

Сейчас `BaseProvider.provider_name` = `self.__class__.__name__.replace("Provider","").lower()`
→ у всех провайдеров литерал `"openai"`, потому что тип один. Ломает читаемость
логов и сообщений об ошибках стартовой валидации (`provider "openai"` вместо `glm`).

- `BaseProvider.__init__(self, config, config_manager=None, provider_name=None)`;
  `self.provider_name = provider_name or <class-derived fallback>`.
- `src/providers/__init__.py:_build_provider` уже получает `provider_name` и
  сейчас его выбрасывает — передать в конструктор.
- Обновить докстринг `__init__` («Auto-derives provider_name from class name»).
- Тест: `_build_provider("glm", {...})` → `instance.provider_name == "glm"`;
  прямое конструирование без имени → старый fallback.

## Шаг 2 — identity-заголовки на всех сервисах (исходный п.2)

`_build_identity_headers` вызывается только в
`src/services/chat_service/chat_service.py:57`. `embedding_service.py:46` и
`transcription_service.py:78` уходят к апстриму без `extra_headers` — расходящийся
отпечаток между эндпоинтами одного провайдера.

- В обоих сервисах получить `request` (проверить, доходит ли он до этих методов;
  если нет — пробросить из роутера, как в chat), вызвать
  `self._build_identity_headers(provider_instance, request)` и передать
  `extra_headers=` в `provider_instance.embeddings(...)` / `.transcriptions(...)`.
- Проверить, что `embeddings`/`transcriptions` в `src/providers/openai.py` и
  `base.py` принимают `extra_headers` (у `transcriptions` тело multipart —
  убедиться, что `Content-Type` не перетирается: в `_make_request` он
  специально снимается для multipart).
- Тесты: по одному на сервис — клиентский `User-Agent` доезжает до апстрима.

## Шаг 3 — denylist вместо whitelist + валидация `headers:` (исходный п.3)

Полный форвард клиентских заголовков **обязан** иметь denylist, иначе наверх
уедут наши/транспортные заголовки.

Не форвардить (case-insensitive), константа рядом с `_extract_passthrough_headers`:
`authorization`, `host`, `content-length`, `content-type`, `connection`,
`transfer-encoding`, `te`, `upgrade`, `keep-alive`, `proxy-authorization`,
`accept-encoding`, `cookie`, `x-forwarded-*`, `x-real-ip`.

`authorization` дополнительно уже защищён в `_merge_request_headers`
(INVARIANT над классом) — denylist это дублирует намеренно, ближе к источнику.

Валидация статических `headers:` из YAML (сейчас `base.py:99` берёт dict как есть,
`X-Title: 12345` падает только на первом запросе):
- ключи и значения — строки, иначе `PROVIDER_CONFIG_ERROR` на старте;
- явный `Authorization` в `headers:` → ошибка, а не тихое игнорирование;
- hop-by-hop имена из denylist в `headers:` → ошибка.
Симметрично тому, как сейчас fail-fast сделан для `passthrough_headers`
(`base.py:122–133`) — этот код заменяется валидацией `headers:`.

Тесты: denylist-заголовок не уходит; нестроковое значение / `Authorization` /
hop-by-hop в `headers:` → отказ при конструировании.

## Проверка

`/run-tests` целиком (изменены base provider, base service, config_manager,
три сервиса). Отдельно глазами: `grep -rn "opencode\|passthrough_headers" src config CLAUDE.md`
должен быть пуст.

## Порядок и коммиты

0 → 1 → 3 → 2. Шаг 2 последним: он трогает больше всего сервисов и опирается на
уже устоявшуюся сигнатуру `_build_identity_headers` из шагов 0/3.
Четыре коммита, по шагу на коммит.
