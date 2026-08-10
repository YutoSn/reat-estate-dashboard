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
  // 世帯年収から求める予算。income が未入力のあいだは価格の安さで評価する。
  budget: {
    income: null,
    downPayment: 0,
    buildingBudget: 0,
    repaymentRatio: 25,
    landArea: 0,
    onlyAffordable: false,
  },
};

// 観点の並び順は /api/meta に従う（init で埋める）
let DIMENSION_ORDER = [];

const BUDGET_STORAGE_KEY = 'sumai-budget';

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
  DIMENSION_ORDER = meta.dimensions.map((dim) => dim.key);

  meta.dimensions.forEach((dim) => {
    state.weights[dim.key] = dim.default_weight;
  });

  renderTimelineBanner();
  setupBudgetControls();
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

// ---------------------------------------------------------------- 予算
// 世帯年収から「いくらまで出せるか」を出し、市区町村ごとの必要額と突き合わせる。
// 金額はすべて万円で扱う（画面の入力に合わせるため）。

function budgetActive() {
  return Number(state.budget.income) > 0;
}

function onlyAffordable() {
  return budgetActive() && state.budget.onlyAffordable;
}

/** 借入可能額（万円）。元利均等返済の現価から求める。 */
function loanableAmount() {
  const model = state.meta.budget_model;
  const monthly = (state.budget.income * state.budget.repaymentRatio) / 100 / 12;
  const rate = model.interest_rate / 100 / 12;
  const months = model.loan_years * 12;
  if (rate === 0) return monthly * months;
  return (monthly * (1 - (1 + rate) ** -months)) / rate;
}

/** 予算の総額（万円）＝ 自己資金 ＋ 借入可能額。 */
function totalBudget() {
  return state.budget.downPayment + loanableAmount();
}

/**
 * その市区町村で買うことになる土地の広さ（㎡）。
 * 「地域の中央値」を選んだときは実際の取引面積を使うが、
 * 取引の少ない自治体では中央値が800㎡といった値になるので上下限で挟む。
 */
function landAreaFor(row) {
  if (state.budget.landArea > 0) return state.budget.landArea;
  const median = row.raw_land_area_median;
  if (!median) return null;
  const model = state.meta.budget_model;
  return Math.min(model.land_area_max, Math.max(model.land_area_min, median));
}

/**
 * その市区町村で家を建てるのに要る総額（万円）と、予算に対する適合度。
 * 単価か面積が取れない自治体は評価しない（null を返す）。
 */
function budgetFit(row) {
  if (!budgetActive()) return null;
  const unitPrice = row.raw_land_unit_price;
  const area = landAreaFor(row);
  if (!unitPrice || !area) return null;

  const landCost = (unitPrice * area) / 10000;
  const required = landCost + state.budget.buildingBudget;
  if (required <= 0) return null;

  const budget = totalBudget();
  const ratio = budget / required;
  return {
    area,
    landCost,
    required,
    ratio,
    withinBudget: ratio >= 1,
    score: budgetFitScore(ratio),
  };
}

/**
 * 予算比を0〜100点に変換する。
 *
 * 予算より安ければ安いほど良い、とはしていない。予算の範囲に収まった時点で
 * 資金面の条件は満たしており、そこから先は子育て環境や利便性で選ぶべきだからだ。
 * そのため「余裕を持って届く」ところで頭打ちにし、届かない側だけを強く減点する。
 */
function budgetFitScore(ratio) {
  const model = state.meta.budget_model;
  const floor = model.reachable_floor;
  const comfort = model.comfortable_margin;
  if (ratio <= floor) return 0;
  if (ratio >= comfort) return 100;
  if (ratio < 1) return (80 * (ratio - floor)) / (1 - floor);
  return 80 + (20 * (ratio - 1)) / (comfort - 1);
}

function setupBudgetControls() {
  const model = state.meta.budget_model;
  state.budget.buildingBudget = model.building_budget;
  state.budget.repaymentRatio = model.repayment_ratio;
  state.budget.landArea = model.land_area;
  Object.assign(state.budget, loadStoredBudget());

  const ratioSelect = document.getElementById('budget-ratio');
  model.repayment_ratio_options.forEach((value) => {
    const option = el('option', null, `${value}%`);
    option.value = String(value);
    ratioSelect.append(option);
  });
  ratioSelect.value = String(state.budget.repaymentRatio);

  const areaSelect = document.getElementById('budget-area');
  model.land_area_options.forEach((value) => {
    const option = el('option', null, value === 0 ? 'その地域の中央値' : `${value}㎡`);
    option.value = String(value);
    areaSelect.append(option);
  });
  areaSelect.value = String(state.budget.landArea);

  const income = document.getElementById('budget-income');
  const down = document.getElementById('budget-down');
  const building = document.getElementById('budget-building');
  income.value = state.budget.income ?? '';
  down.value = String(state.budget.downPayment);
  building.value = String(state.budget.buildingBudget);

  const onChange = () => {
    const value = Number(income.value);
    state.budget.income = value > 0 ? value : null;
    state.budget.downPayment = Math.max(0, Number(down.value) || 0);
    state.budget.buildingBudget = Math.max(0, Number(building.value) || 0);
    state.budget.repaymentRatio = Number(ratioSelect.value);
    state.budget.landArea = Number(areaSelect.value);
    storeBudget();
    renderBudgetSummary();
    renderRanking();
  };

  [income, down, building].forEach((input) => input.addEventListener('input', onChange));
  [ratioSelect, areaSelect].forEach((select) => select.addEventListener('change', onChange));

  const onlyCheckbox = document.getElementById('budget-only');
  onlyCheckbox.checked = state.budget.onlyAffordable;
  onlyCheckbox.addEventListener('change', () => {
    state.budget.onlyAffordable = onlyCheckbox.checked;
    storeBudget();
    renderRanking();
  });

  document.getElementById('budget-clear').addEventListener('click', () => {
    state.budget.income = null;
    state.budget.onlyAffordable = false;
    income.value = '';
    onlyCheckbox.checked = false;
    storeBudget();
    renderBudgetSummary();
    renderRanking();
  });

  renderBudgetSummary();
}

function renderBudgetSummary() {
  const summary = document.getElementById('budget-summary');
  const onlyWrap = document.getElementById('budget-only-wrap');
  summary.innerHTML = '';

  const active = budgetActive();
  summary.hidden = !active;
  onlyWrap.hidden = !active;
  if (!active) return;

  const model = state.meta.budget_model;
  const loan = loanableAmount();
  const total = totalBudget();

  [
    ['借入の目安', `${fmt(loan)}万円`],
    ['＋ 自己資金', `${fmt(state.budget.downPayment)}万円`],
    ['＝ 使える予算', `${fmt(total)}万円`],
  ].forEach(([label, value], index) => {
    const item = el('div', `budget-item${index === 2 ? ' is-total' : ''}`);
    item.append(el('span', 'budget-item-label', label));
    item.append(el('span', 'budget-item-value', value));
    summary.append(item);
  });

  summary.append(
    el(
      'p',
      'budget-note',
      `年収${fmt(state.budget.income)}万円の${state.budget.repaymentRatio}%を`
        + `年間返済に充て、金利${model.interest_rate}%・${model.loan_years}年・元利均等で`
        + `返す前提です。実際の借入可能額は勤務先や既存の借入で変わります。`,
    ),
  );
}

function loadStoredBudget() {
  try {
    const raw = window.localStorage.getItem(BUDGET_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function storeBudget() {
  try {
    window.localStorage.setItem(BUDGET_STORAGE_KEY, JSON.stringify(state.budget));
  } catch {
    // プライベートブラウジング等で保存できなくても動作には影響しない
  }
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

/**
 * 観点別スコアを重み付けして総合点にする。
 * 世帯年収が入っているときだけ、「手が届きやすさ」を価格の安さではなく
 * その予算に対する適合度に差し替える。
 */
function computeComposite(row, fit = undefined) {
  const budgetFitResult = fit === undefined ? budgetFit(row) : fit;

  let total = 0;
  let weightSum = 0;
  DIMENSION_ORDER.forEach((key) => {
    const value = dimensionValue(row, key, budgetFitResult);
    const weight = state.weights[key] ?? 0;
    if (value === null || value === undefined || weight <= 0) return;
    total += value * weight;
    weightSum += weight;
  });
  return weightSum > 0 ? total / weightSum : null;
}

function dimensionValue(row, key, fit) {
  if (key === 'affordability' && budgetActive()) {
    return fit ? fit.score : null;
  }
  return row[`dim_${key}`];
}

function dimensionLabel(dim) {
  if (dim.key === 'affordability' && budgetActive()) return '予算適合';
  return dim.short_label || dim.label;
}

// ---------------------------------------------------------------- ランキング
async function loadRanking() {
  const pref = document.getElementById('rank-pref').value;
  const query = pref ? `?pref_code=${pref}&limit=500` : '?limit=500';
  state.ranking = await api(`/api/ranking${query}`);
  renderRanking();
}

function renderRankingHead() {
  const thead = document.querySelector('#ranking-table thead');
  thead.innerHTML = '';
  const tr = el('tr');
  tr.append(el('th', 'col-rank', '#'));
  tr.append(el('th', null, '市区町村'));
  tr.append(el('th', 'num', '総合'));
  state.meta.dimensions.forEach((dim) => {
    const th = el('th', 'num', dimensionLabel(dim));
    th.title = dim.description;
    tr.append(th);
  });
  tr.append(el('th', 'num', '都心まで'));
  tr.append(el('th', 'num', '土地単価'));
  if (budgetActive()) tr.append(el('th', 'num', '必要額'));
  tr.append(el('th', 'num', '2050年'));
  thead.append(tr);
}

function renderRanking() {
  renderRankingHead();
  const tbody = document.querySelector('#ranking-table tbody');
  const empty = document.getElementById('ranking-empty');
  tbody.innerHTML = '';

  const minPop = Number(document.getElementById('rank-size').value || 0);
  const rows = state.ranking
    .map((row) => {
      const fit = budgetFit(row);
      return { ...row, _fit: fit, _composite: computeComposite(row, fit) };
    })
    .filter((row) => row._composite !== null)
    .filter((row) => !minPop || (row.raw_pop_total ?? 0) >= minPop)
    // 年収を消したときに絞り込みだけが残って全件消えないよう、両方が立っているときだけ効かせる
    .filter((row) => !onlyAffordable() || row._fit?.withinBudget)
    .sort((a, b) => b._composite - a._composite);

  empty.hidden = rows.length > 0;
  empty.textContent = onlyAffordable()
    ? 'この予算に収まる市区町村が見つかりません。条件をゆるめてください。'
    : 'データがありません。';

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
    DIMENSION_ORDER.forEach((key) =>
      tr.append(scoreCell(dimensionValue(row, key, row._fit))),
    );

    const distance = row.raw_tokyo_distance_km;
    tr.append(el('td', 'num', distance === null || distance === undefined
      ? '—'
      : `${fmt(distance, 0)}km`));

    const price = row.raw_land_unit_price;
    tr.append(el('td', 'num', price ? `${fmt(price / 10000, 1)}万円/㎡` : '—'));

    if (budgetActive()) tr.append(requiredCostCell(row._fit));

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

function requiredCostCell(fit) {
  const td = el('td', 'num');
  if (!fit) {
    td.textContent = '—';
    td.title = '土地の取引が少なく、必要額を出せません。';
    return td;
  }
  td.append(el('span', 'cost-value', `${fmt(fit.required)}万円`));
  td.append(
    el(
      'span',
      `cost-badge ${fit.withinBudget ? 'is-within' : 'is-over'}`,
      fit.withinBudget ? '予算内' : `予算の${fmt(1 / fit.ratio, 1)}倍`,
    ),
  );
  td.title = `土地${fmt(fit.area)}㎡ ${fmt(fit.landCost)}万円 ＋ 建物・諸費用`
    + ` ${fmt(state.budget.buildingBudget)}万円`;
  return td;
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

  const fit = budgetFit(scores);
  const composite = computeComposite(scores, fit);
  document.getElementById('detail-composite').textContent =
    composite === null ? '—' : fmt(composite, 0);

  renderRadar(scores, fit);
  renderHighlights(metrics, fit);
  renderTimeline(data.child_projection, data.stages);
  renderPriceChart(data.price_trend);
  renderPopChart(data.stats_trend);
  renderDistricts(districts);
  renderMetrics(metrics, years);
}

function renderRadar(scores, fit) {
  destroyChart('radar');
  const canvas = document.getElementById('radar-chart');
  const labels = state.meta.dimensions.map((d) => dimensionLabel(d));
  const values = state.meta.dimensions.map(
    (d) => dimensionValue(scores, d.key, fit) ?? 0,
  );

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

function renderHighlights(metrics, fit) {
  const container = document.getElementById('detail-highlights');
  container.innerHTML = '';

  const items = [];

  if (budgetActive()) {
    items.push(
      fit
        ? {
          label: `予算 ${fmt(totalBudget())}万円 に対して`,
          value: `${fmt(fit.required)}万円`,
          note: fit.withinBudget
            ? `予算内（土地${fmt(fit.area)}㎡ ${fmt(fit.landCost)}万円＋建物等）`
            : `${fmt(fit.required - totalBudget())}万円 足りない（土地${fmt(fit.area)}㎡）`,
          tone: fit.withinBudget ? 'good' : 'warn',
        }
        : {
          label: '予算との比較',
          value: '—',
          note: '土地の取引が少なく必要額を出せません',
        },
    );
  }

  items.push(
    {
      label: '東京駅まで',
      value: metrics.tokyo_distance_km !== null && metrics.tokyo_distance_km !== undefined
        ? `${fmt(metrics.tokyo_distance_km, 0)}km`
        : '—',
      note: metrics.hub_name && metrics.hub_distance_km !== null
        ? `最寄りの中心都市は${metrics.hub_name}（${fmt(metrics.hub_distance_km, 0)}km）`
        : '直線距離。路線網は反映していません',
    },
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
  );

  items.forEach((item) => {
    const card = el('div', `highlight${item.tone ? ` is-${item.tone}` : ''}`);
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
    ['東京駅までの距離', fmt(metrics.tokyo_distance_km, 0) + 'km', '直線距離'],
    [
      `最寄り中心都市（${metrics.hub_name || '—'}）まで`,
      fmt(metrics.hub_distance_km, 0) + 'km',
      '直線距離',
    ],
    ['可住地人口密度', fmt(metrics.pop_density_habitable) + '人/km²', years.habitable_area],
    ['取引された土地の広さ', fmt(metrics.land_area_median) + '㎡', '直近10年の中央値'],
  ];

  rows.forEach(([label, value, note]) => {
    const card = el('div', 'metric-card');
    card.append(el('span', 'metric-label', label));
    card.append(el('span', 'metric-value', value));
    const caption = typeof note === 'string' ? note : note ? `${note}年` : '—';
    card.append(el('span', 'metric-year', caption));
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
      labels: state.meta.dimensions.map((d) => dimensionLabel(d)),
      datasets: data.map((item, index) => ({
        label: item.municipality.municipality_name,
        data: state.meta.dimensions.map(
          (d) => dimensionValue(item.scores, d.key, budgetFit(item.scores)) ?? 0,
        ),
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
      dim.key === 'affordability' && budgetActive() ? '予算適合' : dim.label,
      (item) => fmt(dimensionValue(item.scores, dim.key, budgetFit(item.scores)), 0),
    ]),
    ['東京駅までの距離', (item) => {
      const distance = item.scores.raw_tokyo_distance_km;
      return distance === undefined || distance === null ? '—' : `${fmt(distance, 0)}km`;
    }],
    ['土地㎡単価', (item) => {
      const price = item.scores.raw_land_unit_price;
      return price ? `${fmt(price / 10000, 1)}万円` : '—';
    }],
    ...(budgetActive()
      ? [['必要額（土地＋建物）', (item) => {
        const fit = budgetFit(item.scores);
        return fit ? `${fmt(fit.required)}万円` : '—';
      }]]
      : []),
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
