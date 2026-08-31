# Config — rules for `config/**` and `src/core/config_manager.py`

* All provider connections, model mappings and access control live in YAML. No hardcoded
  endpoints or model names in code.
* Config changes take effect within the reload interval (5s). No restart required — and the
  provider cache is rebuilt on reload, with the old pools drained, not killed.
* Env-backed settings are read **once, at construction** into the frozen `Settings` dataclass
  (`config_manager.settings`; each field's env var is its upper-cased name): env vars cannot
  change without a restart, so a per-access read would only cost the hot path a parse and move
  malformed-value failures into requests. No direct `os.getenv` in providers or services.
* A new config field needs, in the same commit: the YAML schema update, the `Settings`
  field, and the entry in `CLAUDE.md`.
* On the server, `config/` and `.env` are authoritative — a deploy syncs `src/` only and
  never touches them.
