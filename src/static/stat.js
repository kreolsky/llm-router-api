let chart = null;
let currentDays = '30';

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
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
    bg: [hexToRgba(c,0.7), hexToRgba(c,0.45), hexToRgba(c,0.25)],
  };
}

async function loadFilter(name) {
  const resp = await fetch('/stat/api/' + name);
  if (!resp.ok) throw new Error(name + ' fetch failed');
  return await resp.json();
}

function renderCheckboxes(containerId, items, type) {
  const el = document.getElementById(containerId);
  el.innerHTML = items.map((v, i) => {
    const id = type + '-' + i;
    return '<label><input type="checkbox" id="' + id + '" value="' + v + '" onchange="updateChart()"> ' + v + '</label>';
  }).join('');
}

function selectAll(type) {
  const list = document.getElementById(type + '-list');
  list.querySelectorAll('input').forEach(cb => { cb.checked = true; });
  updateChart();
}

function deselectAll(type) {
  const list = document.getElementById(type + '-list');
  list.querySelectorAll('input').forEach(cb => { cb.checked = false; });
  updateChart();
}

function checkedValues(type) {
  return [...document.querySelectorAll('#' + type + '-list input:checked')].map(cb => cb.value);
}

async function updateChart() {
  const users = checkedValues('user');
  const models = checkedValues('model');
  const params = new URLSearchParams();
  if (users.length) params.set('users', users.join(','));
  if (models.length) params.set('models', models.join(','));
  if (currentDays) params.set('days', currentDays);

  const status = document.getElementById('status');
  status.className = 'loader';
  status.textContent = 'Loading...';

  try {
    const resp = await fetch('/stat/api/usage?' + params.toString());
    if (!resp.ok) throw new Error('usage fetch failed');
    const data = await resp.json();
    renderChart(data.series);
  } catch(e) {
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

  series.forEach((s, i) => {
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

document.querySelectorAll('.period-bar button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.period-bar button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentDays = btn.dataset.days;
    updateChart();
  });
});

(async function init() {
  try {
    const [users, models] = await Promise.all([loadFilter('users'), loadFilter('models')]);
    renderCheckboxes('user-list', users, 'user');
    renderCheckboxes('model-list', models, 'model');
    selectAll('user');
    selectAll('model');
  } catch(e) {
    document.getElementById('status').className = 'error';
    document.getElementById('status').textContent = 'Failed to load filters: ' + e.message;
  }
})();
