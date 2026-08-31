# Model pricing — derivation notes

How the effective per-token prices in `config/model_info.yaml` (prod, authoritative)
were derived for the two "estimated cost" groups: the z.ai subscription model and
the locally-hosted models. Stored pricing is **USD per token** (OpenRouter
convention, see the INVARIANT in `src/core/usage_db/writer.py`) and cost is
frozen at write time, so these rates only affect **new** `usage_events` rows.

Cost formula (src/core/usage_db/writer.py:206-209):

```
cost = max(prompt - cached, 0) * prompt_price
     + cached * input_cache_read      # falls back to prompt_price when absent
     + completion * completion_price
```

## glm/pro — z.ai GLM Coding Plan

Not a list price: the model is only reachable through the coding subscription,
so the rate is the subscription cost spread over measured traffic.

- Subscription: **USD 432 / year**
- Measured traffic: **470M tokens / year** → blended 432 / 470M ≈ **9.19e-7 $/tok**
- Split input:output at the z.ai **list ratio 1:3.667**:
  - `prompt: 0.0000009032`
  - `completion: 0.000003312` (= 3.667 × prompt)
  - (Consistency check: this pair averages to 9.19e-7 at an implied measured mix
    of ~150 prompt tokens per completion token — matches the observed ~170:1.)

### Cache rate

The plan meters quota in **credits** with per-token multipliers
(docs.z.ai/devpack/overview, GLM-5.3):

```
credits = (input × 6.9 + cached_input × 1.7 + output × 24) / 10 000
```

The subscription dollar is therefore spent on quota units, and per-token prices
must be proportional to the multipliers:

- `input_cache_read = prompt × 1.7 / 6.9 ≈ prompt × 0.246` →
  **`input_cache_read: 0.0000002225`**
- Off-peak 50% discount is a uniform scale factor — it does not change the ratio.

Calibration source: the [Charge Type page](https://z.ai/manage-apikey/billing)
reports input / cached-input / output token totals that can be diffed against
our `usage_events` sums for the same window.

## local/orange/* and system/interface — hardware ownership

Same RTX 3090 box; the rate is the cost of owning it for a year, not a list price.

- Card USD 800 (amortized) + 434 kWh × USD 0.25 (24/7: 350 W generating,
  30 W idle) = **USD 909 / year**
- Measured traffic: **1.25B tokens / year** → blended 909 / 1.25B ≈ **7.27e-7 $/tok**
- Prices are weighted by GPU-time per token: prefill ~600 tok/s vs decode
  20.7 tok/s → weights **1:30** (prompt:completion):
  - `prompt: 0.0000003727`
  - `completion: 0.00001118`
  - (Consistency check: averages to 7.27e-7 at an implied measured mix of
    ~29.5 prompt tokens per completion token — matches the observed ~23–44:1.)

### Cache rate

A cache hit skips prefill entirely — zero GPU-time — so a cached input token's
marginal cost is ~0 and the box cost is carried by the decode-weighted
completion price:

- **`input_cache_read: 0`**

## History

- **2026-08-31**: added the `input_cache_read` values above (prod
  `config/model_info.yaml`, hot-reloaded; backup `model_info.yaml.bak-20260831`).
  Before this, the missing key fell back to the full prompt price — with a
  97.8% cache-hit rate on glm/pro this overstated its recorded cost ~3.5×.
  Historical `glm/pro` rows were recomputed in-place with the same formula
  (781 rows, $76.61 → $22.01; DB snapshot `usage.db.bak-20260831` in the
  container). Recomputation is **not** the norm: cost is normally frozen at
  write time by design.

## Maintenance

- Edit **prod** `config/model_info.yaml` (authoritative; never push local
  config over it). Hot-reload picks it up within ~5 s; check container logs for
  `Configuration reloaded` and the absence of `model_info` soft-validation
  warnings.
- To recalibrate, aggregate a measurement window from the DB (read-only,
  **inside the container** — a host-side sqlite open resets the WAL over
  VirtioFS, see the INVARIANT(data-loss) on the `usage_data` volume):

  ```sql
  SELECT model_id, SUM(prompt_tokens), SUM(cached_tokens), SUM(completion_tokens)
  FROM usage_events WHERE timestamp > :window_start GROUP BY model_id;
  ```
