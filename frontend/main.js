import './style.css';
import Chart from 'chart.js/auto';

// ---------------------------------------------------------------- 状態
const state = {
  meta: null,
  weights: {},
  ranking: [],
  prefectures: [],
  compareCodes: [],
  charts: {},
};

const DIMENSION_ORDER = ['childcare', 'medical', 'future', 'living', 'affordability'];

const PALETTE = ['#1f6f5c', '#c96f3f', '#4a6fa5', '#8a5a83', '#5c8a4a', '#a5504a'];

// ---------------------------------------------------------------- ユーティリティ
const api = async (path) => {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
};

const fmt = (value, digits = 0) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return Number(value).toLocaleString('ja-JP', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

const fmtYen = (value) => (value === null || value === undefined ? '—' : `${fmt(value)}円`);

const fmtSigned = (value, digits = 1) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${fmt(value, digits)}`;
};

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const destroyChart = (key) => {
  if (state.charts[key]) {
    state.charts[key].destroy();
    delete state.charts[key];
  }
};

// ---------------------------------------------------------------- 初期化
async function init() {
  setupTabs();

  const [meta, prefectures] = await Promise.all([
    api('/api/meta'),
    api('/api/prefectures'),
  ]);
  state.meta = meta;
  state.prefectures = prefectures;

  meta.dimensions.forEach((dim) => {
    state.weights[dim.key] = dim.default_weight;
  });

  renderTimelineBanner();
  renderWeightControls();
  fillPrefectureSelects();

  document.getElementById('reset-weights').addEventListener('click', () => {
    state.meta.dimensions.forEach((dim) => {
      state.weights[dim.key] = dim.default_weight;
    });
    renderWeightControls();
    renderRanking();
  });

  document.getElementById('rank-pref').addEventListener('change', loadRanking);
  document.getElementById('rank-size').addEventListener('change', renderRanking);
  await loadRanking();

  setupDetailView();
  setupCompareView();
}

function setupTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('is-active'));
      document.querySelectorAll('.view').forEach((v) => v.classList.remove('is-active'));
      tab.classList.add('is-active');
      document.getElementById(`view-${tab.dataset.view}`).classList.add('is-active');
      if (tab.dataset.view === 'hazard') ensureHazardMap();
    });
  });
}

function renderTimelineBanner() {
  const banner = document.getElementById('timeline-banner');
  banner.innerHTML = '';
  const intro = el('div', 'banner-intro');
  intro.append(el('strong', null, '今のお子さんが小さいうちに決める、これからの15年'));
  intro.append(
    el(
      'p',
      null,
      '家を建てる判断は「今の便利さ」より「子どもが学校に通う頃どうなっているか」で決まります。',
    ),
  );
  banner.append(intro);

  const row = el('div', 'banner-stages');
  state.meta.stages.forEach((stage) => {
    const card = el('div', 'stage-card');
    card.append(el('span', 'stage-label', stage.label));
    card.append(el('span', 'stage-year', `${stage.start_year}〜${stage.end_year}年`));
    card.append(el('span', 'stage-age', `${stage.start_age}〜${stage.end_age}歳`));
    row.append(card);
  });
  banner.append(row);
}

// ---------------------------------------------------------------- 重み
function renderWeightControls() {
  const container = document.getElementById('weights');
  container.innerHTML = '';

  state.meta.dimensions.forEach((dim) => {
    const wrap = el('div', 'weight-item');
    const head = el('div', 'weight-head');
    head.append(el('span', 'weight-label', dim.label));
    const pct = el('span', 'weight-value', `${Math.round(state.weights[dim.key] * 100)}%`);
    head.append(pct);
    wrap.append(head);

    const input = document.createElement('input');
    input.type = 'range';
    input.min = '0';
    input.max = '50';
    input.step = '5';
    input.value = String(Math.round(state.weights[dim.key] * 100));
    input.addEventListener('input', () => {
      state.weights[dim.key] = Number(input.value) / 100;
      pct.textContent = `${input.value}%`;
      renderRanking();
    });
    wrap.append(input);
    wrap.append(el('p', 'weight-desc', dim.description));
    container.append(wrap);
  });
}

function computeComposite(row) {
  let total = 0;
  let weightSum = 0;
  DIMENSION_ORDER.forEach((key) => {
    const value = row[`dim_${key}`];
    const weight = state.weights[key] ?? 0;
    if (value === null || value === undefined || weight <= 0) return;
    total += value * weight;
    weightSum += weight;
  });
  return weightSum > 0 ? total / weightSum : null;
}

// ---------------------------------------------------------------- ランキング
async function loadRanking() {
  const pref = document.getElementById('rank-pref').value;
  const query = pref ? `?pref_code=${pref}&limit=500` : '?limit=500';
  state.ranking = await api(`/api/ranking${query}`);
  renderRanking();
}

function renderRanking() {
  const tbody = document.querySelector('#ranking-table tbody');
  const empty = document.getElementById('ranking-empty');
  tbody.innerHTML = '';

  const minPop = Number(document.getElementById('rank-size').value || 0);
  const rows = state.ranking
    .map((row) => ({ ...row, _composite: computeComposite(row) }))
    .filter((row) => row._composite !== null)
    .filter((row) => !minPop || (row.raw_pop_total ?? 0) >= minPop)
    .sort((a, b) => b._composite - a._composite);

  empty.hidden = rows.length > 0;

  rows.slice(0, 100).forEach((row, index) => {
    const tr = el('tr');
    tr.append(el('td', 'col-rank', String(index + 1)));

    const nameCell = el('td');
    const link = el('button', 'link-button', row.municipality_name || row.municipality_code);
    link.addEventListener('click', () => openDetail(row.prefecture_code, row.municipality_code));
    nameCell.append(link);
    const pop = row.raw_pop_total;
    nameCell.append(
      el(
        'span',
        'sub-label',
        `${row.prefecture_name || ''}${pop ? `　${fmt(pop)}人` : ''}`,
      ),
    );
    tr.append(nameCell);

    tr.append(scoreCell(row._composite, true));
    DIMENSION_ORDER.forEach((key) => tr.append(scoreCell(row[`dim_${key}`])));

    const price = row.raw_land_unit_price;
    tr.append(el('td', 'num', price ? `${fmt(price / 10000, 1)}万円/㎡` : '—'));

    const outlook = row.raw_proj_pop_change_2050;
    const outlookCell = el('td', 'num');
    if (outlook === null || outlook === undefined) {
      outlookCell.textContent = '—';
    } else {
      outlookCell.textContent = `${fmtSigned(outlook, 0)}%`;
      outlookCell.style.color = outlook >= 0 ? 'var(--accent)' : 'var(--warm)';
    }
    tr.append(outlookCell);
    tbody.append(tr);
  });
}

function scoreCell(value, emphasize = false) {
  const td = el('td', `num${emphasize ? ' emphasize' : ''}`);
  if (value === null || value === undefined) {
    td.textContent = '—';
    return td;
  }
  const bar = el('div', 'score-cell');
  const fill = el('span', 'score-bar');
  fill.style.width = `${Math.max(2, Math.min(100, value))}%`;
  fill.style.background = scoreColor(value);
  bar.append(fill);
  bar.append(el('span', 'score-num', fmt(value, 0)));
  td.append(bar);
  return td;
}

function scoreColor(value) {
  if (value >= 70) return '#1f6f5c';
  if (value >= 45) return '#7ba05b';
  if (value >= 25) return '#d9a441';
  return '#c96f3f';
}

// ---------------------------------------------------------------- 共通セレクト
function fillPrefectureSelects() {
  ['rank-pref', 'detail-pref', 'compare-pref'].forEach((id) => {
    const select = document.getElementById(id);
    if (id !== 'rank-pref') select.innerHTML = '<option value="">選択してください</option>';
    state.prefectures.forEach((pref) => {
      const option = el('option', null, pref.name);
      option.value = pref.code;
      select.append(option);
    });
  });
}

async function loadCities(prefCode, selectId) {
  const select = document.getElementById(selectId);
  select.innerHTML = '<option value="">選択してください</option>';
  if (!prefCode) return;
  const cities = await api(`/api/cities/${prefCode}`);
  cities.forEach((city) => {
    const option = el('option', null, city.municipality);
    option.value = city.municipality_code;
    select.append(option);
  });
}

// ---------------------------------------------------------------- 詳細
function setupDetailView() {
  document.getElementById('detail-pref').addEventListener('change', async (event) => {
    await loadCities(event.target.value, 'detail-city');
  });
  document.getElementById('detail-city').addEventListener('change', (event) => {
    if (event.target.value) loadDetail(event.target.value);
  });
}

async function openDetail(prefCode, cityCode) {
  document.querySelector('.tab[data-view="detail"]').click();
  const prefSelect = document.getElementById('detail-pref');
  prefSelect.value = prefCode;
  await loadCities(prefCode, 'detail-city');
  document.getElementById('detail-city').value = cityCode;
  await loadDetail(cityCode);
}

async function loadDetail(cityCode) {
  const [data, districts] = await Promise.all([
    api(`/api/municipality/${cityCode}`),
    api(`/api/municipality/${cityCode}/districts`),
  ]);

  document.getElementById('detail-empty').hidden = true;
  document.getElementById('detail-body').hidden = false;

  const { municipality, metrics, scores, observation_years: years } = data;
  document.getElementById('detail-name').textContent = municipality.municipality_name;
  document.getElementById('detail-sub').textContent =
    `${municipality.prefecture_name}　人口 ${fmt(metrics.pop_total)}人`;

  const composite = computeComposite(scores);
  document.getElementById('detail-composite').textContent =
    composite === null ? '—' : fmt(composite, 0);

  renderRadar(scores);
  renderHighlights(metrics, scores);
  renderTimeline(data.child_projection, data.stages);
  renderPriceChart(data.price_trend);
  renderPopChart(data.stats_trend);
  renderDistricts(districts);
  renderMetrics(metrics, years);
}

function renderRadar(scores) {
  destroyChart('radar');
  const canvas = document.getElementById('radar-chart');
  const labels = state.meta.dimensions.map((d) => d.label);
  const values = state.meta.dimensions.map((d) => scores[`dim_${d.key}`] ?? 0);

  state.charts.radar = new Chart(canvas, {
    type: 'radar',
    data: {
      labels,
      datasets: [
        {
          data: values,
          backgroundColor: 'rgba(31, 111, 92, 0.18)',
          borderColor: '#1f6f5c',
          borderWidth: 2,
          pointBackgroundColor: '#1f6f5c',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        r: {
          min: 0,
          max: 100,
          ticks: { stepSize: 25, backdropColor: 'transparent', font: { size: 10 } },
          pointLabels: { font: { size: 12 } },
        },
      },
    },
  });
}

function renderHighlights(metrics, scores) {
  const container = document.getElementById('detail-highlights');
  container.innerHTML = '';

  const items = [
    {
      label: '住宅地の土地単価',
      value: metrics.land_unit_price ? `${fmt(metrics.land_unit_price / 10000, 1)}万円/㎡` : '—',
      note: metrics.land_price_change_10y !== null && metrics.land_price_change_10y !== undefined
        ? `10年で ${fmtSigned(metrics.land_price_change_10y)}%`
        : '推移データ不足',
    },
    {
      label: '保育所（未就学児1000人あたり）',
      value: metrics.nurseries_per_1k_children
        ? `${fmt(metrics.nurseries_per_1k_children, 1)}か所`
        : '—',
      note: '多いほど預け先を探しやすい',
    },
    {
      label: '小学校 教員1人あたり児童数',
      value: metrics.pupils_per_teacher ? `${fmt(metrics.pupils_per_teacher, 1)}人` : '—',
      note: '少ないほど手厚い',
    },
    {
      label: '医師（人口1万人あたり）',
      value: metrics.doctors_per_10k ? `${fmt(metrics.doctors_per_10k, 1)}人` : '—',
      note: '乳幼児期に効く',
    },
    {
      label: '2050年までの人口見通し',
      value: metrics.proj_pop_change_2050 !== null && metrics.proj_pop_change_2050 !== undefined
        ? `${fmtSigned(metrics.proj_pop_change_2050)}%`
        : '—',
      note: '社人研の将来推計人口',
    },
    {
      label: '年少人口の10年変化',
      value: metrics.young_pop_change_10y !== null && metrics.young_pop_change_10y !== undefined
        ? `${fmtSigned(metrics.young_pop_change_10y)}%`
        : '—',
      note: '子育て世帯に選ばれているか',
    },
  ];

  items.forEach((item) => {
    const card = el('div', 'highlight');
    card.append(el('span', 'highlight-label', item.label));
    card.append(el('span', 'highlight-value', item.value));
    card.append(el('span', 'highlight-note', item.note));
    container.append(card);
  });
}

function renderTimeline(projection, stages) {
  const container = document.getElementById('detail-timeline');
  container.innerHTML = '';

  if (!projection || projection.length === 0) {
    container.append(el('p', 'empty-note', '推計に必要な年齢別人口が不足しています。'));
    return;
  }

  projection.forEach((item) => {
    const card = el('div', 'timeline-card');
    card.append(el('span', 'timeline-stage', item.label));
    card.append(el('span', 'timeline-year', `${item.target_year}年ごろ・${item.age_range}`));
    card.append(el('span', 'timeline-pop', `${fmt(item.population)}人`));
    card.append(el('span', 'timeline-age', `1学年あたり約 ${fmt(item.per_grade)}人`));

    const rate = item.settle_rate;
    const badge = el('span', `timeline-badge ${rate >= 1 ? 'up' : rate >= 0.9 ? 'neutral' : 'down'}`);
    badge.textContent = `定着率 ${fmt(rate, 2)}`;
    badge.title = rate >= 1
      ? '生まれた数より多い＝子育て世帯が転入している'
      : '生まれた数より少ない＝就学前後に転出がある';
    card.append(badge);

    card.append(el('span', 'timeline-basis', item.basis));
    container.append(card);
  });
}

function renderPriceChart(trend) {
  destroyChart('price');
  const canvas = document.getElementById('price-chart');
  // 集計途中の年は件数が数分の一しかなく、末尾が急落したように見えるので除く
  const rows = (trend || [])
    .filter((r) => !r.is_partial)
    .filter((r) => r.land_unit_price || r.house_price);

  state.charts.price = new Chart(canvas, {
    type: 'line',
    data: {
      labels: rows.map((r) => r.year),
      datasets: [
        {
          label: '土地㎡単価（住宅地・中央値）',
          data: rows.map((r) => r.land_unit_price),
          borderColor: '#1f6f5c',
          backgroundColor: 'rgba(31,111,92,.1)',
          yAxisID: 'y',
          spanGaps: true,
          tension: 0.25,
        },
        {
          label: '戸建て取引価格（中央値）',
          data: rows.map((r) => r.house_price),
          borderColor: '#c96f3f',
          backgroundColor: 'rgba(201,111,63,.1)',
          yAxisID: 'y1',
          spanGaps: true,
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        y: {
          position: 'left',
          title: { display: true, text: '円/㎡' },
          ticks: { callback: (v) => `${(v / 10000).toFixed(0)}万` },
        },
        y1: {
          position: 'right',
          title: { display: true, text: '戸建て価格' },
          grid: { drawOnChartArea: false },
          ticks: { callback: (v) => `${(v / 10000000).toFixed(1)}千万` },
        },
      },
    },
  });
}

function renderPopChart(trend) {
  destroyChart('pop');
  const canvas = document.getElementById('pop-chart');
  const rows = (trend || []).filter((r) => r.pop_total || r.pop_0_14);

  state.charts.pop = new Chart(canvas, {
    type: 'line',
    data: {
      labels: rows.map((r) => r.year),
      datasets: [
        {
          label: '総人口',
          data: rows.map((r) => r.pop_total ?? r.pop_census ?? null),
          borderColor: '#4a6fa5',
          yAxisID: 'y',
          spanGaps: true,
          tension: 0.25,
        },
        {
          label: '15歳未満人口',
          data: rows.map((r) => r.pop_0_14 ?? null),
          borderColor: '#c96f3f',
          yAxisID: 'y1',
          spanGaps: true,
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        y: { position: 'left', title: { display: true, text: '総人口' } },
        y1: {
          position: 'right',
          title: { display: true, text: '15歳未満' },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

function renderDistricts(districts) {
  const tbody = document.querySelector('#district-table tbody');
  tbody.innerHTML = '';
  if (!districts || districts.length === 0) {
    const tr = el('tr');
    const td = el('td', 'empty-note', '対象となる取引がありません。');
    td.colSpan = 4;
    tr.append(td);
    tbody.append(tr);
    return;
  }
  districts.slice(0, 40).forEach((row) => {
    const tr = el('tr');
    tr.append(el('td', null, row.district_name));
    tr.append(el('td', 'num', `${fmt(row.land_unit_price / 10000, 1)}万円`));
    tr.append(el('td', 'num', `${fmt(row.median_area)}㎡`));
    tr.append(el('td', 'num', fmt(row.deals)));
    tbody.append(tr);
  });
}

function renderMetrics(metrics, years) {
  const container = document.getElementById('detail-metrics');
  container.innerHTML = '';

  const rows = [
    ['総人口', fmt(metrics.pop_total) + '人', years.pop_total],
    ['15歳未満人口', fmt(metrics.pop_0_14) + '人', years.pop_0_14],
    ['年少人口比率', fmt(metrics.young_ratio, 1) + '%', years.pop_0_14],
    ['高齢化率', fmt(metrics.aging_ratio, 1) + '%', years.pop_total],
    ['保育所密度', fmt(metrics.nurseries_per_1k_children, 1) + 'か所/千人', years.nurseries],
    ['小学校数', fmt(metrics.elem_schools) + '校', years.elem_pupils],
    ['1校あたり児童数', fmt(metrics.pupils_per_school) + '人', years.elem_pupils],
    ['教員1人あたり児童数', fmt(metrics.pupils_per_teacher, 1) + '人', years.elem_teachers],
    ['子ども1人あたり児童福祉費', fmtYen(metrics.child_welfare_per_child), years.child_welfare_exp],
    ['財政力指数', fmt(metrics.fiscal_index, 2), years.fiscal_index],
    ['医師密度', fmt(metrics.doctors_per_10k, 1) + '人/万人', years.doctors],
    ['診療所密度', fmt(metrics.clinics_per_10k, 1) + '施設/万人', years.clinics],
    ['一戸建比率', fmt(metrics.detached_ratio, 1) + '%', years.dwellings_occupied],
    ['持ち家比率', fmt(metrics.ownership_ratio, 1) + '%', years.dwellings_occupied],
    ['社会増減', fmtSigned(metrics.net_migration_rate, 1) + '人/千人', years.pop_total],
    ['昼夜間人口比率', fmt(metrics.day_night_ratio, 1) + '%', years.pop_total],
  ];

  rows.forEach(([label, value, year]) => {
    const card = el('div', 'metric-card');
    card.append(el('span', 'metric-label', label));
    card.append(el('span', 'metric-value', value));
    card.append(el('span', 'metric-year', year ? `${year}年` : '—'));
    container.append(card);
  });
}

// ---------------------------------------------------------------- 比較
function setupCompareView() {
  document.getElementById('compare-pref').addEventListener('change', async (event) => {
    await loadCities(event.target.value, 'compare-city');
  });
  document.getElementById('compare-add').addEventListener('click', () => {
    const code = document.getElementById('compare-city').value;
    if (!code || state.compareCodes.includes(code) || state.compareCodes.length >= 6) return;
    state.compareCodes.push(code);
    renderCompare();
  });
}

async function renderCompare() {
  const chips = document.getElementById('compare-chips');
  const result = document.getElementById('compare-result');
  chips.innerHTML = '';

  if (state.compareCodes.length === 0) {
    result.hidden = true;
    return;
  }

  const data = await api(`/api/compare?codes=${state.compareCodes.join(',')}`);

  data.forEach((item, index) => {
    const chip = el('span', 'chip');
    chip.style.borderColor = PALETTE[index % PALETTE.length];
    chip.append(el('span', null, item.municipality.municipality_name));
    const remove = el('button', 'chip-remove', '×');
    remove.addEventListener('click', () => {
      state.compareCodes = state.compareCodes.filter(
        (c) => c !== item.municipality.municipality_code,
      );
      renderCompare();
    });
    chip.append(remove);
    chips.append(chip);
  });

  result.hidden = false;
  renderCompareRadar(data);
  renderCompareTable(data);
}

function renderCompareRadar(data) {
  destroyChart('compareRadar');
  const canvas = document.getElementById('compare-radar');

  state.charts.compareRadar = new Chart(canvas, {
    type: 'radar',
    data: {
      labels: state.meta.dimensions.map((d) => d.label),
      datasets: data.map((item, index) => ({
        label: item.municipality.municipality_name,
        data: state.meta.dimensions.map((d) => item.scores[`dim_${d.key}`] ?? 0),
        borderColor: PALETTE[index % PALETTE.length],
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 3,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { r: { min: 0, max: 100, ticks: { stepSize: 25 } } },
    },
  });
}

function renderCompareTable(data) {
  const table = document.getElementById('compare-table');
  const thead = table.querySelector('thead');
  const tbody = table.querySelector('tbody');
  thead.innerHTML = '';
  tbody.innerHTML = '';

  const headRow = el('tr');
  headRow.append(el('th', null, '項目'));
  data.forEach((item) => headRow.append(el('th', 'num', item.municipality.municipality_name)));
  thead.append(headRow);

  const rows = [
    ['総合スコア', (item) => fmt(computeComposite(item.scores), 0)],
    ...state.meta.dimensions.map((dim) => [
      dim.label,
      (item) => fmt(item.scores[`dim_${dim.key}`], 0),
    ]),
    ['土地㎡単価', (item) => {
      const price = item.scores.raw_land_unit_price;
      return price ? `${fmt(price / 10000, 1)}万円` : '—';
    }],
    ...['nursery', 'elementary', 'junior'].map((stage) => [
      `${stage === 'nursery' ? '保育園期' : stage === 'elementary' ? '小学校期' : '中学校期'}の同年代`,
      (item) => {
        const found = (item.child_projection || []).find((p) => p.stage === stage);
        return found ? `${fmt(found.population)}人` : '—';
      },
    ]),
  ];

  rows.forEach(([label, accessor]) => {
    const tr = el('tr');
    tr.append(el('td', null, label));
    data.forEach((item) => tr.append(el('td', 'num', accessor(item))));
    tbody.append(tr);
  });
}

// ---------------------------------------------------------------- ハザード
let hazardLoaded = false;
async function ensureHazardMap() {
  if (hazardLoaded) return;
  hazardLoaded = true;
  const [{ default: L }] = await Promise.all([
    import('leaflet'),
    import('leaflet/dist/leaflet.css'),
  ]);

  const map = L.map('map').setView([36.2, 139.8], 9);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap &copy; CARTO',
  }).addTo(map);

  const overlays = {
    洪水浸水想定区域: 'https://disaportaldata.gsi.go.jp/raster/01_flood_l2_shinsuishin_data/{z}/{x}/{y}.png',
    土砂災害警戒区域: 'https://disaportaldata.gsi.go.jp/raster/05_dosekiryukeikaikuiki/{z}/{x}/{y}.png',
    津波浸水想定: 'https://disaportaldata.gsi.go.jp/raster/04_tsunami_newlegend_data/{z}/{x}/{y}.png',
    '地形分類（地盤リスク）': 'https://cyberjapandata.gsi.go.jp/xyz/experimental_landform/{z}/{x}/{y}.png',
    都市圏活断層図: 'https://cyberjapandata.gsi.go.jp/xyz/afm/{z}/{x}/{y}.png',
  };

  const layers = {};
  Object.entries(overlays).forEach(([name, url]) => {
    layers[name] = L.tileLayer(url, {
      opacity: 0.7,
      attribution: '国土地理院',
    });
  });
  layers['洪水浸水想定区域'].addTo(map);
  L.control.layers(null, layers, { collapsed: false }).addTo(map);

  setTimeout(() => map.invalidateSize(), 200);
}

init().catch((error) => {
  console.error(error);
  document.querySelector('.app-main').prepend(
    el('p', 'empty-note', `データの読み込みに失敗しました: ${error.message}`),
  );
});
