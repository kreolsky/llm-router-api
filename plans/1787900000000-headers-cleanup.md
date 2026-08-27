# Headers cleanup: single identity mode with a denylist

## Decisions

- One identity mode survives: `identity: passthrough`. Every client header is
  forwarded upstream verbatim — the client's own spelling — minus a denylist.
  The whitelist (`DEFAULT_PASSTHROUGH_HEADERS`, `passthrough_headers:`), the
  synthetic `opencode` profile (`SessionRegistry`, `ses_*` ids,
  `identity_version`, `OPENCODE_SESSION_TTL`) and their tests are deleted;
  `identity` accepts only `None` / `"passthrough"`
  (`src/providers/base.py:106`, `config/providers.yaml:6`).
- The denylist lives in one shared module because two layers must agree on
  it: the service layer filters client headers (`src/services/base.py:49`),
  the provider layer validates static `headers:` against the same names
  (`src/providers/base.py:125`). Three groups, case-insensitive
  (`src/core/header_policy.py:58`): client credentials (only the router's key
  from `api_key_env` goes up), transport/hop-by-hop (the router re-serializes
  the body, so client framing values are stale), reverse-proxy topology
  (would leak internal IPs).
- Fail-open is deliberate: an unknown client header IS forwarded. The
  consequence — the denylist must be re-audited whenever a new harness or
  proxy is onboarded — is pinned as an `# INVARIANT:` over the constant
  (`src/core/header_policy.py:12`).
- Static `headers:` from providers.yaml is validated at construction: string
  name/value, no `Authorization` (the key comes from `api_key_env`), no
  transport names — `X-Title: 12345` fails at startup, not on the first
  request. Validation runs before the code-owned `Content-Type` default.
- `provider_name` is the providers.yaml dict key, passed into the constructor
  by the factory (`src/providers/__init__.py:34`,
  `src/providers/base.py:104`); the class-derived name stays as a fallback.
  Fixes logs and startup-validation errors naming every backend "openai".
- Identity headers go to ALL endpoints of a provider, not only chat
  (`src/services/chat_service/chat_service.py:58` was the only caller):
  embeddings and transcriptions build and pass `extra_headers` the same way.
  Multipart Content-Type is unaffected — the denylist strips the client's
  value and `_make_request` pops the static one for multipart bodies.
- `authorization` stays protected twice on purpose: the denylist drops it at
  the source, and `_merge_request_headers` still never overwrites it
  (`src/providers/base.py:341`).

## Risks

- Whitelist removal and the denylist MUST land in one commit: an intermediate
  "forward everything, denylist later" state sends `host` / `content-length` /
  `transfer-encoding` upstream and breaks requests.
- Verbatim casing changes the fingerprint (the whitelist used to canonicalize
  `user-agent` → `User-Agent`). HTTP semantics are unaffected; accepted
  because the header source is now one real agent, not a synthesized profile.
- Deploy: `deploy-server` does not sync `config/` — the server's
  `providers.yaml` is authoritative. If it still carries `identity: opencode`,
  the new code refuses to start (fail-fast by design). Check it before
  rollout and switch to `passthrough` or drop the key.

## Order

Each step is one commit; the order is load-bearing.

1. **Remove whitelist/opencode + add denylist + validate `headers:` — one
   commit.** Delete `src/core/identity_headers.py`,
   `src/core/opencode_identity.py`, `tests/unit/test_identity_headers.py`,
   `tests/unit/test_opencode_identity.py`. In `src/providers/base.py`: drop
   the whitelist compile, `identity_version` and the `opencode` branch;
   identity ∈ {None, "passthrough"} with updated error text; add
   static-`headers:` validation. In `src/services/base.py`:
   `_extract_passthrough_headers(request)` returns everything minus the
   denylist; `_build_identity_headers` loses the `opencode` branch. Drop
   `opencode_session_ttl` from `_ENV_SETTINGS` (`src/core/config_manager.py:169`).
   Clean `config/providers.yaml` comments, rewrite CLAUDE.md (Upstream
   Identity, Process Model, env list) and README, regenerate SYSTEMS.md.
2. **Real provider_name.** Constructor takes `provider_name`; the factory
   passes the config key; docstring updated. Tests: `_build_provider("glm", ...)`
   names the instance "glm"; direct construction keeps the class fallback.
3. **Identity headers on embeddings/transcriptions.** Both services call
   `_build_identity_headers` and pass `extra_headers` into `embeddings()` /
   `transcriptions()`; provider signatures accept it. Tests: one per service —
   the client `User-Agent` reaches the provider call.

## Not doing

- No per-provider denylist configurability: the whitelist knob is deleted,
  not replaced with a denylist knob.
- No canonical-casing normalization: the client's spelling is forwarded as-is.
- No migration path for `identity: opencode` configs — startup fails with
  `Unknown identity profile` by design (see Risks).
- `.env` / `docker-compose.yml` untouched: `OPENCODE_SESSION_TTL` was never
  set there.
- `_extract_passthrough_headers` keeps its name.

## Validation

- Full `/run-tests` (base provider, base service, config_manager and three
  services changed).
- `grep -rn "opencode\|passthrough_headers" src config CLAUDE.md` is empty.
- Live drive on a container built from the new code: streaming and
  non-streaming chat with a client `User-Agent`, plus one embedding call —
  upstream headers observed in debug logs, denylisted header (`x-api-key`)
  confirmed absent.

## Progress

- Landed on `dev`: step 1 = `dc5ea32`, step 2 = `bb7894c`, step 3 = `403ac31`.
- Unit: 423 passed; 3 failures pre-exist on clean HEAD (asyncio timing). Full
  suite: 545 passed, 1 skipped, 10 API failures environmental — the live
  container ran pre-change code (openrouter model id gone upstream;
  deepseek-v4-flash returns empty `content` under a small `max_tokens`).
- Remaining: the live drive above against a rebuilt container; the server
  `providers.yaml` check at deploy time (see Risks).
