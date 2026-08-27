let chart = null;
let currentDays = '30';
let summaryByErrorCode = [];
let logPage = 0;
const PAGE_SIZE = 50;

// ---------------------------------------------------------------------------
// Stat API key (X-Stat-Key header only; prompted and stored on 401)
// ---------------------------------------------------------------------------

function statKey() { return localStorage.getItem('stat_api_key') || ''; }

async function apiFetch(url) {
  const key = statKey();
  let resp = await fetch(url, key ? { headers: { 'X-Stat-Key': key } } : {});
  if (resp.status === 401) {
    const entered = window.prompt('Stat API key required (sent as X-Stat-Key):');
    if (entered !== null) {
      localStorage.setItem('stat_api_key', entered);
      resp = await fetch(url, { headers: { 'X-Stat-Key': entered } });
      if (resp.status === 401) localStorage.removeItem('stat_api_key');
    }
  }
  return resp;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function fmtTokens(n) {
  if (n == null) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}

function fmtCost(usd) {
  if (usd == null) return '—';
  if (usd >= 1) return '$' + usd.toFixed(2);
  if (usd >= 0.01) return '$' + usd.toFixed(3);
  return '$' + usd.toFixed(5);
}

function fmtRate(r) {
  if (r == null) return '—';
  return (r * 100).toFixed(1) + '%';
}

function fmtDuration(ms) {
  if (ms == null) return '—';
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's';
  return Math.round(ms) + 'ms';
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric',
                                       hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function dash(v) { return v == null || v === '' ? '—' : esc(v); }

// ---------------------------------------------------------------------------
// Filters (users / models / period)
// ---------------------------------------------------------------------------

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

const USER_PALETTE = [
  '#58a6ff','#3fb950','#d29922','#f25e5e','#bc8cff',
  '#56d3cc','#ff7b72','#a5d6a7','#9fa8da','#e6c17f',
  '#79c0ff','#7ee787','#e3b341','#ff6b6b','#d2a8ff',
];

function colorForIndex(i) {
  const c = USER_PALETTE[i % USER_PALETTE.length];
  return {
    border: c,
    bg: [hexToRgba(c, 0.7), hexToRgba(c, 0.45), hexToRgba(c, 0.25)],
  };
}

async function loadFilter(name) {
  const resp = await apiFetch('/stat/api/' + name);
  if (!resp.ok) throw new Error(name + ' fetch failed');
  return await resp.json();
}

function renderCheckboxes(containerId, items, type) {
  const el = document.getElementById(containerId);
  el.innerHTML = items.map((v, i) => {
    const id = type + '-' + i;
    return '<label><input type="checkbox" id="' + id + '" value="' + esc(v) + '" onchange="refreshAll()"> ' +
           (v === '' ? '—' : esc(v)) + '</label>';
  }).join('');
}

function selectAll(type) {
  document.getElementById(type + '-list').querySelectorAll('input').forEach(cb => { cb.checked = true; });
  refreshAll();
}

function deselectAll(type) {
  document.getElementById(type + '-list').querySelectorAll('input').forEach(cb => { cb.checked = false; });
  refreshAll();
}

function checkedValues(type) {
  return [...document.querySelectorAll('#' + type + '-list input:checked')].map(cb => cb.value);
}

function sharedParams() {
  const params = new URLSearchParams();
  const users = checkedValues('user');
  const models = checkedValues('model');
  if (users.length) params.set('users', users.join(','));
  if (models.length) params.set('models', models.join(','));
  if (currentDays) params.set('days', currentDays);
  return params;
}

// ---------------------------------------------------------------------------
// Summary cards + breakdown tables
// ---------------------------------------------------------------------------

function card(label, value, note) {
  return '<div class="card"><div class="card-label">' + label + '</div>' +
         '<div class="card-value">' + value + '</div>' +
         (note ? '<div class="card-note">' + note + '</div>' : '') + '</div>';
}

function renderSummary(data) {
  const t = data.totals;
  const cards = [
    card('Requests', fmtTokens(t.requests),
         t.errors ? fmtTokens(t.errors) + ' errors (' + fmtRate(t.error_rate) + ')' : 'no errors'),
    card('Prompt tokens', fmtTokens(t.prompt_tokens),
         fmtTokens(t.cached_tokens) + ' cached · hit ' + fmtRate(t.cache_hit_rate)),
    card('Completion tokens', fmtTokens(t.completion_tokens),
         fmtTokens(t.reasoning_tokens) + ' reasoning'),
    card('Total tokens', fmtTokens(t.total_tokens), null),
    card('Cost', fmtCost(t.cost_usd),
         t.unpriced ? t.unpriced + ' requests unpriced' : null),
  ];
  document.getElementById('cards').innerHTML = cards.join('');

  renderBreakdownTable('by-user-table', data.by_user, 'user');
  renderBreakdownTable('by-model-table', data.by_model, 'model');
  renderBreakdownTable('by-provider-table', data.by_provider, 'provider');

  // Refresh the error-code filter options from the breakdown (NULL bucket = "—")
  summaryByErrorCode = data.by_error_code;
  const select = document.getElementById('log-error-code');
  const selected = select.value;
  select.innerHTML = '<option value="">all error codes</option>' +
    data.by_error_code.map(e =>
      '<option value="' + (e.error_code == null ? 'none' : esc(e.error_code)) + '">' +
      (e.error_code == null ? '—' : esc(e.error_code)) + ' (' + e.count + ')</option>').join('');
  select.value = selected;
}

function renderBreakdownTable(tableId, rows, labelKey) {
  const table = document.getElementById(tableId);
  if (!rows.length) {
    table.innerHTML = '<tbody><tr><td class="empty">no data</td></tr></tbody>';
    return;
  }
  const head = '<thead><tr><th>' + labelKey + '</th><th>req</th><th>err</th>' +
    '<th class="num">prompt</th><th class="num">cached</th><th class="num">compl</th>' +
    '<th class="num">total</th><th class="num">cost</th></tr></thead>';
  const body = '<tbody>' + rows.map(r =>
    '<tr><td class="cell-key" title="' + esc(r[labelKey] || '') + '">' + dash(r[labelKey]) + '</td>' +
    '<td>' + fmtTokens(r.requests) + '</td>' +
    '<td' + (r.errors ? ' class="err"' : '') + '>' + (r.errors || 0) + '</td>' +
    '<td class="num">' + fmtTokens(r.prompt_tokens) + '</td>' +
    '<td class="num">' + fmtTokens(r.cached_tokens) + '</td>' +
    '<td class="num">' + fmtTokens(r.completion_tokens) + '</td>' +
    '<td class="num">' + fmtTokens(r.total_tokens) + '</td>' +
    '<td class="num">' + fmtCost(r.cost_usd) + '</td></tr>').join('') + '</tbody>';
  table.innerHTML = head + body;
}

// ---------------------------------------------------------------------------
// Token chart (unchanged stacked daily chart)
// ---------------------------------------------------------------------------

async function updateChart() {
  const status = document.getElementById('status');
  try {
    const resp = await apiFetch('/stat/api/usage?' + sharedParams().toString());
    if (!resp.ok) throw new Error('usage fetch failed');
    const data = await resp.json();
    renderChart(data.series);
  } catch (e) {
    status.className = 'error';
    status.textContent = 'Error: ' + e.message;
  }
}

function renderChart(series) {
  const canvas = document.getElementById('chart');
  const status = document.getElementById('status');

  if (!series.length) {
    status.className = 'loader';
    status.textContent = 'No data for the selected filters.';
    canvas.style.display = 'none';
    return;
  }

  status.style.display = 'none';
  canvas.style.display = 'block';

  const datasets = [];
  const stackGroups = {};
  let groupIdx = 0;

  series.forEach(s => {
    const key = s.user + '|' + s.model;
    if (!(key in stackGroups)) {
      stackGroups[key] = 'stack' + groupIdx;
      groupIdx++;
    }
  });

  series.forEach((s) => {
    const colors = colorForIndex(Object.keys(stackGroups).indexOf(s.user + '|' + s.model));
    const stackId = stackGroups[s.user + '|' + s.model];
    const label = s.user + ' / ' + s.model;

    datasets.push({
      label: label + ' prompt',
      data: s.dates.map((d, j) => ({ x: d, y: s.prompt[j] })),
      backgroundColor: colors.bg[0],
      borderColor: colors.border,
      borderWidth: 0,
      stack: stackId,
      fill: true,
      pointRadius: 0,
    });
    datasets.push({
      label: label + ' cached',
      data: s.dates.map((d, j) => ({ x: d, y: s.cached[j] })),
      backgroundColor: colors.bg[1],
      borderColor: colors.border,
      borderWidth: 0,
      borderDash: [2, 2],
      stack: stackId,
      fill: true,
      pointRadius: 0,
    });
    datasets.push({
      label: label + ' completion',
      data: s.dates.map((d, j) => ({ x: d, y: s.completion[j] })),
      backgroundColor: colors.bg[2],
      borderColor: colors.border,
      borderWidth: 0,
      borderDash: [5, 3],
      stack: stackId,
      fill: true,
      pointRadius: 0,
    });
  });

  if (chart) chart.destroy();

  const ctx = canvas.getContext('2d');
  chart = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: { color: '#c9d1d9', boxWidth: 12, padding: 4, font: { size: 10 } },
        },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: 'day', tooltipFormat: 'yyyy-MM-dd', displayFormats: { day: 'MMM dd' } },
          ticks: { color: '#8b949e', maxTicksLimit: 20 },
          grid: { color: 'rgba(48,54,61,0.5)' },
        },
        y: {
          stacked: true,
          title: { display: true, text: 'Tokens', color: '#8b949e' },
          ticks: { color: '#8b949e', callback: v => v >= 1000 ? (v/1000).toFixed(1)+'k' : v },
          grid: { color: 'rgba(48,54,61,0.5)' },
        },
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Request log
// ---------------------------------------------------------------------------

function statusClass(code) {
  if (code == null) return '';
  if (code >= 500) return 'st-5xx';
  if (code >= 400) return 'st-4xx';
  return 'st-2xx';
}

function logRowHtml(r) {
  const tokens = (!r.prompt_tokens && !r.completion_tokens)
    ? '—' : fmtTokens(r.prompt_tokens) + ' / ' + fmtTokens(r.completion_tokens);
  const errBadge = r.error_code
    ? '<span class="badge badge-err">' + esc(r.error_code) + '</span>'
    : (r.status_code >= 400 ? '<span class="badge badge-null">—</span>' : '');
  const expandable = r.error_message || r.api_key_hash || r.request_id;
  return '<tr class="log-row' + (expandable ? ' expandable' : '') + '" data-req="' + r.id + '">' +
    '<td class="cell-time">' + fmtTime(r.timestamp) + '</td>' +
    '<td class="cell-key" title="' + esc(r.project_name) + '">' + esc(r.project_name) + '</td>' +
    '<td class="cell-key" title="' + esc(r.model_id) + '">' + dash(r.model_id) + '</td>' +
    '<td>' + dash(r.provider_name) + '</td>' +
    '<td>' + esc(r.endpoint) + '</td>' +
    '<td>' + (r.stream ? 'sse' : '') + '</td>' +
    '<td class="num">' + tokens + '</td>' +
    '<td class="num">' + fmtCost(r.cost_usd) + '</td>' +
    '<td class="num">' + fmtDuration(r.duration_ms) + '</td>' +
    '<td class="' + statusClass(r.status_code) + '">' + (r.status_code == null ? '—' : r.status_code) + '</td>' +
    '<td>' + errBadge + '</td>' +
    '</tr>' +
    (expandable
      ? '<tr class="log-detail" data-req="' + r.id + '"><td colspan="11">' +
        '<div>request_id: <code>' + esc(r.request_id) + '</code>' +
        (r.client_ip ? ' · ip: <code>' + esc(r.client_ip) + '</code>' : '') +
        (r.api_key_hash ? ' · key: <code>' + esc(r.api_key_hash) + '</code>' : '') + '</div>' +
        (r.error_message ? '<div class="err-text">' + esc(r.error_message) + '</div>' : '') +
        '</td></tr>'
      : '');
}

async function updateLog() {
  const params = sharedParams();
  params.set('status', document.getElementById('log-status').value);
  const errorCode = document.getElementById('log-error-code').value;
  if (errorCode) params.set('error_code', errorCode);
  const requestId = document.getElementById('log-request-id').value.trim();
  if (requestId) params.set('request_id', requestId);
  params.set('limit', PAGE_SIZE);
  params.set('offset', logPage * PAGE_SIZE);

  const table = document.getElementById('log-table');
  try {
    const resp = await apiFetch('/stat/api/requests?' + params.toString());
    if (!resp.ok) throw new Error('requests fetch failed');
    const data = await resp.json();

    if (!data.requests.length) {
      table.innerHTML = '<tbody><tr><td class="empty">no requests match the filters</td></tr></tbody>';
    } else {
      const head = '<thead><tr><th>time</th><th>user</th><th>model</th><th>provider</th>' +
        '<th>endpoint</th><th></th><th class="num">tok p/c</th><th class="num">cost</th>' +
        '<th class="num">dur</th><th>status</th><th>error</th></tr></thead>';
      table.innerHTML = head + '<tbody>' + data.requests.map(logRowHtml).join('') + '</tbody>';
      table.querySelectorAll('tr.expandable').forEach(tr => {
        tr.addEventListener('click', () => {
          const detail = table.querySelector('tr.log-detail[data-req="' + tr.dataset.req + '"]');
          if (detail) detail.classList.toggle('open');
        });
      });
    }

    const from = data.total === 0 ? 0 : logPage * PAGE_SIZE + 1;
    const to = Math.min((logPage + 1) * PAGE_SIZE, data.total);
    document.getElementById('log-page').textContent = from + '–' + to + ' of ' + data.total;
    document.getElementById('log-prev').disabled = logPage === 0;
    document.getElementById('log-next').disabled = to >= data.total;
  } catch (e) {
    table.innerHTML = '<tbody><tr><td class="empty err">Error: ' + esc(e.message) + '</td></tr></tbody>';
  }
}

function resetLogPage() { logPage = 0; updateLog(); }
function logPrev() { if (logPage > 0) { logPage--; updateLog(); } }
function logNext() { logPage++; updateLog(); }

// ---------------------------------------------------------------------------
// Orchestration
// ---------------------------------------------------------------------------

async function updateSummary() {
  try {
    const resp = await apiFetch('/stat/api/summary?' + sharedParams().toString());
    if (!resp.ok) throw new Error('summary fetch failed');
    renderSummary(await resp.json());
  } catch (e) {
    document.getElementById('cards').innerHTML =
      '<div class="card"><div class="card-value error">Error: ' + esc(e.message) + '</div></div>';
  }
}

function refreshAll() {
  updateSummary();
  updateChart();
  resetLogPage();
}

document.querySelectorAll('.period-bar button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.period-bar button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentDays = btn.dataset.days;
    refreshAll();
  });
});

(async function init() {
  try {
    const [users, models] = await Promise.all([loadFilter('users'), loadFilter('models')]);
    renderCheckboxes('user-list', users, 'user');
    renderCheckboxes('model-list', models, 'model');
    selectAll('user');
    selectAll('model');
  } catch (e) {
    document.getElementById('status').className = 'error';
    document.getElementById('status').textContent = 'Failed to load filters: ' + e.message;
  }
})();
