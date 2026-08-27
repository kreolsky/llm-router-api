# Usage stats — rules for `src/core/usage_db.py`, `src/api/stat_page.py`, `/stat/**`

* **One row per request**, errors included; cost is frozen at write time from the merged
  capabilities pricing. The middleware creates the per-request holder, services only enrich
  it — see the `ARCH:` block at the top of `usage_db.py` before touching either side.
* The gateway runs **one uvicorn worker** on purpose: the OpenCode session registry, the
  capabilities cache and the SQLite writer are process-local singletons that extra workers
  would silently fork into independent copies. `PRAGMA busy_timeout=5000` is set regardless.
* `STAT_API_KEY`, when set, is required as an `X-Stat-Key` **header** on every `/stat/api/*`
  endpoint — **never as a query param**, because the logging middleware logs full URLs.
  `GET /stat/` and `/stat/static` stay open: the page is what prompts for the key.
* Anything rendered into the dashboard HTML is escaped. Usage rows carry client-supplied
  strings (model names, project names) and reach the page as stored content — an unescaped
  helper has already been a stored-XSS fix here.
