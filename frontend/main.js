import './style.css';
import Chart from 'chart.js/auto';

// ---------------------------------------------------------------- 状態
const state = {
  meta: null,
  weights: {},
  ranking: [],
  prefectures: [],
  // 「詳しく見る・比べる」で選んでいる市区町村。1件なら詳細だけ、
  // 2件以上なら比較も出す。focusCode が詳細を表示している1件。
  selectedCodes: [],
  focusCode: null,
  detailCache: new Map(),
  districtCache: new Map(),
  pediatricCache: new Map(),
  cityNames: new Map(),
  charts: {},
  // 推移グラフの表示。実額のままだと水準差の大きい市区町村が重ねられない。
  trendMode: 'absolute',
  lastTrendData: null,
  // 弱点の扱い。floor を下回った観点があるぶんだけ総合点から引く。
  balance: {
    floor: 50,
    penaltyPerPoint: 0.5,
    exclude: false,
  },
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
const BALANCE_STORAGE_KEY = 'sumai-balance';

// 色は CSS 変数を唯一の定義にする。ここで持つとダークモードで追随しないため。
const cssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/**
 * 比較用の系列色。順番は固定で、色覚特性のある人でも隣同士が見分けられるか
 * （OKLab の色差）と、描画面とのコントラストを検証したうえで並べてある。
 * 使い回さず、常にこの順に割り当てる。
 *
 * 都度 CSS から読むのは、OSのライト／ダーク切り替えに追随させるため。
 */
const SERIES_SLOTS = 6;
const seriesColor = (index) => cssVar(`--series-${(index % SERIES_SLOTS) + 1}`);

/** #rrggbb を rgba() に変換する（塗りの薄い面を作るため）。 */
function withAlpha(hex, alpha) {
  const value = hex.replace('#', '');
  const int = parseInt(
    value.length === 3 ? value.split('').map((c) => c + c).join('') : value,
    16,
  );
  return `rgba(${(int >> 16) & 255}, ${(int >> 8) & 255}, ${int & 255}, ${alpha})`;
}

/** Chart.js の目盛り・凡例・グリッドを、いまの配色に合わせる。 */
function applyChartTheme() {
  Chart.defaults.color = cssVar('--chart-ink');
  Chart.defaults.borderColor = cssVar('--chart-grid');
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
}

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
  applyChartTheme();
  // OSのライト／ダーク切り替えに、グラフの色も追随させる
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    applyChartTheme();
    renderRanking();
    if (state.selectedCodes.length > 0) renderSelection();
  });

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
  setupBalanceControls();
  renderScoreLogic();
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
  document.getElementById('rank-station').addEventListener('change', renderRanking);
  document.getElementById('rank-commerce').addEventListener('change', renderRanking);
  await loadRanking();

  setupDetailView();
  setupTrendControls();
  setupLoanView();
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

function loadStored(key) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function store(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // プライベートブラウジング等で保存できなくても動作には影響しない
  }
}

const loadStoredBudget = () => loadStored(BUDGET_STORAGE_KEY);
const storeBudget = () => store(BUDGET_STORAGE_KEY, state.budget);
const storeBalance = () => store(BALANCE_STORAGE_KEY, state.balance);

// ---------------------------------------------------------------- 弱点補正
function setupBalanceControls() {
  const model = state.meta.balance_model;
  state.balance.floor = model.floor;
  state.balance.penaltyPerPoint = model.penalty_per_point;
  state.balance.exclude = model.exclude_below_floor;
  Object.assign(state.balance, loadStored(BALANCE_STORAGE_KEY));

  const floorSelect = document.getElementById('balance-floor');
  model.floor_options.forEach((value) => {
    const option = el('option', null, value === 0 ? '補正しない' : `${value}点`);
    option.value = String(value);
    floorSelect.append(option);
  });
  floorSelect.value = String(state.balance.floor);

  const exclude = document.getElementById('balance-exclude');
  exclude.checked = state.balance.exclude;

  // 説明文は件数を数え直す必要があるので renderRanking の側で更新する
  const onChange = () => {
    state.balance.floor = Number(floorSelect.value);
    state.balance.exclude = exclude.checked;
    exclude.disabled = state.balance.floor === 0;
    storeBalance();
    renderRanking();
  };
  floorSelect.addEventListener('change', onChange);
  exclude.addEventListener('change', onChange);
  exclude.disabled = state.balance.floor === 0;
  renderBalanceNote();
}

/**
 * 各基準点で何件が残るかを、いま表示しているランキングから数える。
 *
 * 観点どうしは構造的にぶつかる（都心に近いほど戸建て比率と価格の点は下がる）ので、
 * 「全観点50点以上」は現実には1件も無い。基準点を選ぶときに、その基準で
 * 何件残るのかが分からないと、0件のランキングを見せられて終わってしまう。
 */
function balanceStats() {
  const mins = state.ranking
    .map((row) => compositeDetail(row, budgetFit(row)))
    .filter((detail) => detail && detail.weakest)
    .map((detail) => detail.weakest.value);

  const counts = {};
  state.meta.balance_model.floor_options.forEach((floor) => {
    counts[floor] = mins.filter((value) => value >= floor).length;
  });
  return { best: mins.length ? Math.max(...mins) : null, counts };
}

function renderBalanceNote() {
  const note = document.getElementById('balance-note');
  const { floor, penaltyPerPoint, exclude } = state.balance;
  note.innerHTML = '';

  if (!floor) {
    note.textContent = '観点の加重平均をそのまま総合点にします。';
    return;
  }

  if (exclude) {
    const { best, counts } = balanceStats();
    note.append(
      el('span', null, `重みを掛けたどの観点も${floor}点以上の市区町村は `),
    );
    note.append(el('strong', null, `${fmt(counts[floor] ?? 0)}件`));
    note.append(el('span', null, ' です。'));
    if (best !== null) {
      const usable = state.meta.balance_model.floor_options
        .filter((value) => value > 0 && value < floor && (counts[value] ?? 0) > 0);
      note.append(
        el(
          'span',
          null,
          `　いちばんバランスの良い市区町村でも最低の観点は${fmt(best, 0)}点です`
            + `（観点どうしは構造的にぶつかるため、全観点で上位半分は成立しません）。`
            + (usable.length
              ? `${usable.map((v) => `${v}点なら${fmt(counts[v])}件`).join('、')}残ります。`
              : ''),
        ),
      );
    }
    return;
  }

  const example = Math.round((floor - 20) * penaltyPerPoint);
  note.textContent = `いちばん低い観点が${floor}点を1点下回るごとに、`
    + `総合点から${penaltyPerPoint}点引きます`
    + `（最低の観点が20点なら ${example}点の減点）。`
    + `${floor}点以上ならそのままです。`;
}

// ------------------------------------------------------- スコアの出し方
/** 「探す」画面の折りたたみ。観点ごとに、構成指標と計算式を並べる。 */
function renderScoreLogic() {
  const container = document.getElementById('logic-dimensions');
  container.innerHTML = '';

  state.meta.dimensions.forEach((dim) => {
    const block = el('div', 'logic-dim');
    const head = el('div', 'logic-dim-head');
    head.append(el('h3', null, dim.label));
    head.append(el('span', 'logic-weight', `既定 ${Math.round(dim.default_weight * 100)}%`));
    block.append(head);
    block.append(el('p', 'logic-desc', dim.description));

    const list = el('ul', 'logic-metrics');
    state.meta.metrics
      .filter((metric) => metric.dimension === dim.key)
      .forEach((metric) => {
        const item = el('li', 'logic-metric');
        const title = el('div', 'logic-metric-head');
        title.append(el('span', 'logic-metric-name', metric.label));
        title.append(
          el(
            'span',
            `logic-direction ${metric.higher_is_better ? 'is-up' : 'is-down'}`,
            metric.higher_is_better ? '大きいほど高得点' : '小さいほど高得点',
          ),
        );
        item.append(title);
        if (metric.formula) {
          const formula = el('code', 'logic-formula', metric.formula);
          if (metric.unit) formula.append(el('span', 'logic-unit', `　→ ${metric.unit}`));
          item.append(formula);
        }
        item.append(el('p', 'logic-metric-desc', metric.description));
        list.append(item);
      });
    block.append(list);
    container.append(block);
  });
}

/** 「詳しく見る」画面。観点ごとの点数を、指標と元の統計値まで開けるようにする。 */
function renderBreakdown(breakdown, fit, detail) {
  const container = document.getElementById('detail-breakdown');
  container.innerHTML = '';
  if (!breakdown || breakdown.length === 0) return;

  if (detail) {
    const summary = el('p', `breakdown-total${detail.belowFloor ? ' is-penalized' : ''}`);
    if (detail.belowFloor) {
      const weak = state.meta.dimensions.find((d) => d.key === detail.weakest.key);
      summary.textContent =
        `観点の加重平均は ${fmt(detail.mean, 1)}点。`
        + `${weak ? dimensionLabel(weak) : detail.weakest.key}が${fmt(detail.weakest.value, 0)}点で`
        + `基準点${state.balance.floor}点を${fmt(detail.shortfall, 0)}点下回るため`
        + `${fmt(detail.penalty, 1)}点引いて、総合 ${fmt(detail.composite, 1)}点です。`;
    } else if (state.balance.floor) {
      summary.textContent =
        `観点の加重平均は ${fmt(detail.mean, 1)}点。`
        + `どの観点も基準点${state.balance.floor}点を下回っていないので減点はありません。`;
    } else {
      summary.textContent = `観点の加重平均 ${fmt(detail.mean, 1)}点をそのまま総合点にしています。`;
    }
    container.append(summary);
  }

  breakdown.forEach((dim) => {
    // 世帯年収を入れているときは、価格の点数ではなく予算適合の点数を出す
    const overridden = dim.dimension === 'affordability' && budgetActive();
    const score = overridden ? (fit ? fit.score : null) : dim.score;

    const box = el('details', 'breakdown-dim');
    const summary = el('summary', 'breakdown-summary');
    summary.append(el('span', 'breakdown-name', overridden ? '予算適合' : dim.label));

    const bar = el('span', 'breakdown-bar');
    if (score !== null && score !== undefined) {
      const fill = el('span', 'breakdown-bar-fill');
      fill.style.width = `${Math.max(2, Math.min(100, score))}%`;
      fill.style.background = scoreColor(score);
      bar.append(fill);
    }
    summary.append(bar);
    summary.append(el('span', 'breakdown-score', score === null || score === undefined
      ? '—' : fmt(score, 0)));
    summary.append(el('span', 'breakdown-why', weakestNote(dim, overridden, fit)));
    box.append(summary);

    const body = el('div', 'breakdown-body');
    if (overridden) {
      body.append(el('p', 'logic-metric-desc', budgetExplanation(fit)));
    }
    dim.metrics.forEach((metric) => body.append(metricRow(metric)));
    box.append(body);
    container.append(box);
  });
}

/** 観点の見出しに出す一言。何が足を引っ張っているかを名指しする。 */
function weakestNote(dim, overridden, fit) {
  if (overridden) {
    if (!fit) return '必要額を出せません';
    return fit.withinBudget ? '予算内' : '予算を超えます';
  }
  const scored = dim.metrics.filter((m) => m.score !== null && m.score !== undefined);
  if (scored.length === 0) return 'データなし';
  const weakest = scored.reduce((a, b) => (a.score <= b.score ? a : b));
  if (weakest.score >= 50) return '足を引っ張る指標はありません';
  return `${weakest.label}が${weakest.rank ? `${fmt(weakest.rank)}位` : '下位'}`;
}

function budgetExplanation(fit) {
  if (!fit) return '土地の取引が少なく、必要額を出せませんでした。';
  return `必要額 ${fmt(fit.required)}万円（土地${fmt(fit.area)}㎡ ${fmt(fit.landCost)}万円`
    + ` ＋ 建物・諸費用 ${fmt(state.budget.buildingBudget)}万円）に対して`
    + ` 予算 ${fmt(totalBudget())}万円。予算比 ${fmt(fit.ratio, 2)} 倍。`;
}

/**
 * 表示桁数。図書館密度0.115のように1未満の指標は、既定の1桁だと
 * 「0.1」に潰れて自治体間の差が見えなくなるので桁を足す。
 */
function metricDigits(metric) {
  const value = Math.abs(metric.value);
  if (value > 0 && value < 1) return Math.max(metric.digits, 2);
  return metric.digits;
}

function metricRow(metric) {
  const row = el('div', 'breakdown-metric');

  const head = el('div', 'breakdown-metric-head');
  head.append(el('span', 'breakdown-metric-name', metric.label));
  head.append(
    el(
      'span',
      'breakdown-metric-value',
      metric.value === null || metric.value === undefined
        ? '—'
        : `${fmt(metric.value, metricDigits(metric))}${metric.unit === '-' ? '' : metric.unit}`,
    ),
  );

  const rank = el('span', 'breakdown-rank');
  if (metric.rank && metric.total) {
    rank.textContent = `${fmt(metric.total)}中 ${fmt(metric.rank)}位`;
    rank.classList.add(metric.rank <= metric.total / 3 ? 'is-high'
      : metric.rank >= (metric.total * 2) / 3 ? 'is-low' : 'is-mid');
  } else {
    rank.textContent = '順位なし';
  }
  head.append(rank);

  const score = el('span', 'breakdown-metric-score');
  score.textContent = metric.score === null || metric.score === undefined
    ? '—' : `${fmt(metric.score, 0)}点`;
  if (metric.score !== null && metric.score !== undefined) {
    score.style.color = scoreColor(metric.score);
  }
  head.append(score);
  row.append(head);

  if (metric.formula) {
    row.append(el('code', 'logic-formula', metric.formula));
  }

  if (metric.inputs.length > 0) {
    const inputs = el('ul', 'breakdown-inputs');
    metric.inputs.forEach((input) => {
      const item = el('li');
      item.append(el('span', 'input-name', input.label));
      item.append(
        el(
          'span',
          'input-value',
          input.value === null || input.value === undefined
            ? '—'
            : `${fmt(input.value, Number.isInteger(input.value) ? 0 : 2)}${input.unit === '-' ? '' : input.unit}`,
        ),
      );
      item.append(el('span', 'input-year', input.year ? `${input.year}年` : ''));
      inputs.append(item);
    });
    row.append(inputs);
  }

  // 点数が付かなかった指標は、その観点の平均から外れる。理由を明示しないと
  // 「値は出ているのに点数がない」状態が読み手には説明できない。
  if (metric.score === null || metric.score === undefined) {
    const hasValue = metric.value !== null && metric.value !== undefined;
    row.append(
      el(
        'p',
        'logic-metric-desc',
        hasValue
          ? '母数が足りず順位を付けられないため、この観点の平均には入っていません。'
          : 'この指標の値が取れていないため、この観点の平均には入っていません。',
      ),
    );
  }

  return row;
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
 * 観点別スコアを重み付けし、弱点補正を掛けて総合点にする。
 *
 * 世帯年収が入っているときだけ、「手が届きやすさ」を価格の安さではなく
 * その予算に対する適合度に差し替える。
 *
 * 内訳（平均・最低の観点・減点幅）も一緒に返す。総合点だけ出しても
 * 「なぜこの順位なのか」が読めないため。
 */
function compositeDetail(row, fit = undefined) {
  const budgetFitResult = fit === undefined ? budgetFit(row) : fit;

  let total = 0;
  let weightSum = 0;
  let weakest = null;

  DIMENSION_ORDER.forEach((key) => {
    const value = dimensionValue(row, key, budgetFitResult);
    const weight = state.weights[key] ?? 0;
    if (value === null || value === undefined || weight <= 0) return;
    total += value * weight;
    weightSum += weight;
    // 重み0の観点は「見ない」という意思表示なので、低くても弱点にしない
    if (weakest === null || value < weakest.value) weakest = { key, value };
  });

  if (weightSum <= 0) return null;

  const mean = total / weightSum;
  const { floor, penaltyPerPoint } = state.balance;
  const shortfall = floor && weakest ? Math.max(0, floor - weakest.value) : 0;
  const penalty = shortfall * penaltyPerPoint;

  return {
    mean,
    weakest,
    shortfall,
    penalty,
    belowFloor: shortfall > 0,
    composite: Math.max(0, mean - penalty),
  };
}

function computeComposite(row, fit = undefined) {
  const detail = compositeDetail(row, fit);
  return detail ? detail.composite : null;
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
  state.ranking.forEach((row) => {
    if (row.municipality_name) {
      state.cityNames.set(row.municipality_code, row.municipality_name);
    }
  });
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
  // 残る件数は重みや年収でも変わるので、ランキングを描き直すたびに数え直す
  renderBalanceNote();
  const tbody = document.querySelector('#ranking-table tbody');
  const empty = document.getElementById('ranking-empty');
  tbody.innerHTML = '';

  const minPop = Number(document.getElementById('rank-size').value || 0);
  const minStation = Number(document.getElementById('rank-station').value || 0);
  const minCommerce = Number(document.getElementById('rank-commerce').value || 0);
  const excludeWeak = state.balance.floor > 0 && state.balance.exclude;
  const rows = state.ranking
    .map((row) => {
      const fit = budgetFit(row);
      const detail = compositeDetail(row, fit);
      return { ...row, _fit: fit, _detail: detail, _composite: detail?.composite ?? null };
    })
    .filter((row) => row._composite !== null)
    .filter((row) => !minPop || (row.raw_pop_total ?? 0) >= minPop)
    // 「町内に駅がある」は代表駅の乗降客数で判定する。駅が無い自治体には
    // populate 時に 0 を入れてあるので、1以上あるかを見れば足りる。
    .filter((row) => !minStation || (row.raw_station_passengers_max ?? 0) >= minStation)
    .filter((row) => !minCommerce || (row.raw_commerce_density ?? 0) >= minCommerce)
    // 年収を消したときに絞り込みだけが残って全件消えないよう、両方が立っているときだけ効かせる
    .filter((row) => !onlyAffordable() || row._fit?.withinBudget)
    .filter((row) => !excludeWeak || !row._detail.belowFloor)
    .sort((a, b) => b._composite - a._composite);

  empty.hidden = rows.length > 0;
  empty.textContent = onlyAffordable()
    ? 'この予算に収まる市区町村が見つかりません。条件をゆるめてください。'
    : excludeWeak
      ? 'すべての観点が基準点を超える市区町村がありません。基準点を下げてください。'
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

    tr.append(compositeCell(row._detail));
    DIMENSION_ORDER.forEach((key) => {
      const value = dimensionValue(row, key, row._fit);
      // 減点の原因になった観点に印を付ける。総合点が下がった理由をその場で示す。
      const isWeak = row._detail.belowFloor && row._detail.weakest?.key === key;
      tr.append(scoreCell(value, false, isWeak));
    });

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

function scoreCell(value, emphasize = false, isWeak = false) {
  const classes = ['num'];
  if (emphasize) classes.push('emphasize');
  if (isWeak) classes.push('is-weak');
  const td = el('td', classes.join(' '));
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
  if (isWeak) td.title = `この観点が基準点（${state.balance.floor}点）を下回っています`;
  return td;
}

/** 総合点のセル。減点されているときは、平均と減点幅を添える。 */
function compositeCell(detail) {
  const td = scoreCell(detail.composite, true);
  if (!detail.belowFloor) return td;

  td.append(
    el(
      'span',
      'composite-penalty',
      `平均${fmt(detail.mean, 0)} − 弱点${fmt(detail.penalty, 0)}`,
    ),
  );
  const label = state.meta.dimensions.find((d) => d.key === detail.weakest.key);
  td.title = `${label ? dimensionLabel(label) : detail.weakest.key}が`
    + `${fmt(detail.weakest.value, 0)}点で基準点を${fmt(detail.shortfall, 0)}点下回るため、`
    + `平均${fmt(detail.mean, 1)}点から${fmt(detail.penalty, 1)}点引いています`;
  return td;
}

function scoreColor(value) {
  // 系列色とは別系統の4段階。点数を必ず数字でも併記しているので、
  // 色だけで意味を運ばせてはいない。
  if (value >= 70) return cssVar('--score-high');
  if (value >= 45) return cssVar('--score-mid');
  if (value >= 25) return cssVar('--score-low');
  return cssVar('--score-worst');
}

// ---------------------------------------------------------------- 共通セレクト
function fillPrefectureSelects() {
  ['rank-pref', 'detail-pref'].forEach((id) => {
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
    state.cityNames.set(city.municipality_code, city.municipality);
    const option = el('option', null, city.municipality);
    option.value = city.municipality_code;
    select.append(option);
  });
}

/** 市区町村コードから表示名。詳細の取得を待たずに名前を出すために使う。 */
function cityName(code) {
  return state.detailCache.get(code)?.municipality?.municipality_name
    ?? state.cityNames.get(code)
    ?? code;
}

// -------------------------------------------------- 詳しく見る・比べる
// 選択リストは1本。1件なら詳細だけ、2件以上なら比較表も出す。
// 「詳細を見る」と「比べる」は同じ検討の連続した動作なので、画面を分けない。
const MAX_SELECTION = 6;

function setupDetailView() {
  document.getElementById('detail-pref').addEventListener('change', async (event) => {
    await loadCities(event.target.value, 'detail-city');
  });
  document.getElementById('detail-city').addEventListener('change', (event) => {
    if (event.target.value) selectCity(event.target.value);
  });
  document.getElementById('selection-clear').addEventListener('click', () => {
    state.selectedCodes = [];
    state.focusCode = null;
    renderSelection();
  });
}

/** 市区町村を選択リストに加えて、詳細をそこに切り替える。 */
function selectCity(cityCode) {
  if (!state.selectedCodes.includes(cityCode)) {
    if (state.selectedCodes.length >= MAX_SELECTION) {
      showSelectionHint(
        `選べるのは${MAX_SELECTION}件までです。× で外してから選んでください。`,
      );
      return;
    }
    state.selectedCodes.push(cityCode);
  }
  state.focusCode = cityCode;
  showSelectionHint(null);
  renderSelection();
}

function removeCity(cityCode) {
  state.selectedCodes = state.selectedCodes.filter((code) => code !== cityCode);
  if (state.focusCode === cityCode) {
    state.focusCode = state.selectedCodes[state.selectedCodes.length - 1] ?? null;
  }
  showSelectionHint(null);
  renderSelection();
}

function showSelectionHint(message) {
  const hint = document.getElementById('selection-hint');
  hint.textContent = message ?? '';
  hint.hidden = !message;
}

/** 選択の状態を、チップ・比較・詳細にまとめて反映する。 */
async function renderSelection() {
  renderChips();
  document.getElementById('selection-clear').hidden = state.selectedCodes.length === 0;

  const detailBody = document.getElementById('detail-body');
  const empty = document.getElementById('detail-empty');
  const compare = document.getElementById('compare-result');

  if (state.selectedCodes.length === 0) {
    detailBody.hidden = true;
    compare.hidden = true;
    document.getElementById('trend-panel').hidden = true;
    document.getElementById('pop-panel').hidden = true;
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  // 比較表とレーダーは2件以上のときだけ。1件で出しても読むものが無い。
  // 推移のグラフは1件でも出す（重ねる相手が増えるだけ）。
  const requested = state.selectedCodes.join(',');
  const data = await api(`/api/compare?codes=${requested}`);
  // 取得を待つあいだに選択が変わっていたら、古い結果は描かない
  if (state.selectedCodes.join(',') !== requested) return;

  // 並びを選択順に揃える。チップ・レーダー・表・推移で色と順序がずれると読めない。
  const ordered = state.selectedCodes
    .map((code) => data.find((item) => item.municipality.municipality_code === code))
    .filter(Boolean);

  if (ordered.length >= 2) {
    compare.hidden = false;
    renderCompareRadar(ordered);
    renderCompareTable(ordered);
  } else {
    compare.hidden = true;
    destroyChart('compareRadar');
  }
  renderTrends(ordered);

  if (state.focusCode) await loadDetail(state.focusCode);
}

function renderChips() {
  const chips = document.getElementById('selection-chips');
  chips.innerHTML = '';

  state.selectedCodes.forEach((code, index) => {
    const chip = el('span', `chip${code === state.focusCode ? ' is-focus' : ''}`);
    // チップの色は比較レーダーの線の色と合わせる
    chip.style.borderColor = seriesColor(index);

    const name = el('button', 'chip-name', cityName(code));
    name.title = '詳細をこの市区町村に切り替える';
    name.addEventListener('click', () => {
      state.focusCode = code;
      renderSelection();
    });
    chip.append(name);

    const remove = el('button', 'chip-remove', '×');
    remove.title = '選択から外す';
    remove.addEventListener('click', () => removeCity(code));
    chip.append(remove);
    chips.append(chip);
  });
}

async function openDetail(prefCode, cityCode) {
  document.querySelector('.tab[data-view="detail"]').click();
  const prefSelect = document.getElementById('detail-pref');
  prefSelect.value = prefCode;
  await loadCities(prefCode, 'detail-city');
  document.getElementById('detail-city').value = cityCode;
  selectCity(cityCode);
}

async function loadDetail(cityCode) {
  let data = state.detailCache.get(cityCode);
  let districts = state.districtCache.get(cityCode);
  let pediatrics = state.pediatricCache.get(cityCode);
  if (!data || !districts || !pediatrics) {
    [data, districts, pediatrics] = await Promise.all([
      api(`/api/municipality/${cityCode}`),
      api(`/api/municipality/${cityCode}/districts`),
      api(`/api/municipality/${cityCode}/pediatrics`).catch(() => null),
    ]);
    state.detailCache.set(cityCode, data);
    state.districtCache.set(cityCode, districts);
    state.pediatricCache.set(cityCode, pediatrics);
    // 取得を待つあいだに別の市区町村へ切り替わっていたら、古い結果は描かない
    if (state.focusCode !== cityCode) return;
  }

  document.getElementById('detail-empty').hidden = true;
  document.getElementById('detail-body').hidden = false;

  const { municipality, metrics, scores, observation_years: years } = data;
  // 複数選んでいるときは、どれの詳細を見ているのかを見出しでも示す
  document.getElementById('detail-eyebrow').hidden = state.selectedCodes.length < 2;
  document.getElementById('detail-name').textContent = municipality.municipality_name;
  document.getElementById('detail-sub').textContent =
    `${municipality.prefecture_name}　人口 ${fmt(metrics.pop_total)}人`;

  const fit = budgetFit(scores);
  const detail = compositeDetail(scores, fit);
  document.getElementById('detail-composite').textContent =
    detail === null ? '—' : fmt(detail.composite, 0);

  renderRadar(scores, fit);
  renderHighlights(metrics, fit);
  renderBreakdown(data.score_breakdown, fit, detail);
  renderTimeline(data.child_projection, data.stages);
  // 価格と人口の推移は、選んだ市区町村を重ねて renderTrends が描く
  renderDistricts(districts);
  renderPediatrics(pediatrics);
  renderMetrics(metrics, years);
}

function renderPediatrics(data) {
  const tbody = document.querySelector('#pediatric-table tbody');
  const countLabel = document.getElementById('pediatric-count');
  tbody.innerHTML = '';

  const facilities = data?.facilities ?? [];
  countLabel.textContent = data
    ? `15km圏に ${fmt(data.total)}施設`
    : '';

  if (facilities.length === 0) {
    const tr = el('tr');
    const td = el('td', 'empty-note', '15km圏に小児科が見つかりませんでした。');
    td.colSpan = 4;
    tr.append(td);
    tbody.append(tr);
    return;
  }

  facilities.forEach((row) => {
    const tr = el('tr');
    tr.append(el('td', null, row.name || '—'));
    tr.append(el('td', null, row.facility_type || '—'));
    tr.append(el('td', 'address-cell', row.address || '—'));
    tr.append(el('td', 'num', `${fmt(row.distance_km, 1)}km`));
    tbody.append(tr);
  });
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
          backgroundColor: withAlpha(cssVar('--accent'), 0.18),
          borderColor: cssVar('--accent'),
          borderWidth: 2,
          pointBackgroundColor: cssVar('--accent'),
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
      label: '町内の代表駅',
      value: metrics.station_passengers_max
        ? `${fmt(metrics.station_passengers_max / 10000, 1)}万人/日`
        : '駅なし',
      note: metrics.station_passengers_max
        ? `町内に${fmt(metrics.station_count)}駅`
        : '町内に鉄道駅がありません',
      tone: metrics.station_passengers_max ? undefined : 'warn',
    },
    {
      label: '商業施設の密度',
      value: metrics.commerce_density
        ? `${fmt(metrics.commerce_density, 0)}所/km²`
        : '—',
      note: '可住地1km²あたりの店舗・飲食・サービス',
    },
    {
      label: '小児科（15km圏・子ども1万人あたり）',
      value: metrics.pediatric_clinics_catchment
        ? `${fmt(metrics.pediatric_clinics_catchment, 1)}施設`
        : '—',
      note: '分母は15歳未満人口',
    },
    {
      label: '医師（15km圏・1万人あたり）',
      value: metrics.doctors_catchment ? `${fmt(metrics.doctors_catchment, 1)}人` : '—',
      note: metrics.doctors_per_10k
        ? `自市内だけなら ${fmt(metrics.doctors_per_10k, 1)}人`
        : '隣接自治体を含めた圏内で数えています',
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

/**
 * 1本の折れ線を描く。
 *
 * 桁の違う2系列を左右2軸で重ねると、交差する位置が縮尺の取り方だけで決まり、
 * 「単価が戸建て価格を追い越した」といった意味のない読み取りを誘う。
 * 単位が違うものは軸を分けずにグラフを分ける。
 */
function renderLineChart(key, canvasId, { labels, series, axisTitle, axisTick, valueLabel }) {
  destroyChart(key);
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  // 1本のときだけ面を塗る。重ねたときに塗ると下の線が読めなくなる。
  const filled = series.length === 1;

  state.charts[key] = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: series.map((item, index) => ({
        label: item.label,
        data: item.data,
        borderColor: seriesColor(index),
        backgroundColor: filled
          ? withAlpha(seriesColor(index), 0.12)
          : seriesColor(index),
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        spanGaps: true,
        tension: 0.25,
        fill: filled,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        // 1本のときは見出しが系列名を兼ねるので凡例は出さない
        legend: { display: series.length > 1, position: 'top' },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: {
            label: (item) => `${item.dataset.label}: ${valueLabel(item.parsed.y)}`,
          },
        },
      },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { grid: { display: false } },
        // 単位は軸のタイトルに1回だけ出す。目盛りごとに繰り返すと数字が読みにくい
        y: {
          title: { display: true, text: axisTitle },
          ticks: { callback: axisTick },
        },
      },
    },
  });
}

/**
 * 市区町村ごとの年次データを、共通の年軸に載せ替える。
 *
 * 市区町村によって取れている年が違うので、そのまま並べると同じ位置が
 * 別の年を指してしまう。年の和集合を作り、無い年は null（線を継ぐ）にする。
 */
function alignByYear(items, pick) {
  const years = new Set();
  items.forEach((item) => item.rows.forEach((row) => years.add(row.year)));
  const labels = [...years].sort((a, b) => a - b);

  const series = items.map((item) => {
    const byYear = new Map(item.rows.map((row) => [row.year, row]));
    return {
      label: item.label,
      data: labels.map((year) => pick(byYear.get(year)) ?? null),
    };
  });
  return { labels, series };
}

/**
 * 各系列を「共通の基準年＝100」の指数に直す。
 *
 * 渋谷区170万円/㎡ とつくば市3.3万円/㎡ を実額で重ねると、安い側が軸の
 * 底に張り付いて動きが読めない。水準ではなく伸び方を比べたいときのために、
 * 全系列に値がある最も古い年を基準に揃える。
 * 共通の年が無いときは各系列の最初の年を使う（伸び方の比較としては落ちる）。
 */
function toIndexed(labels, series) {
  const common = labels.findIndex(
    (_, i) => series.every((s) => s.data[i] !== null && s.data[i] !== 0),
  );

  const indexed = series.map((s) => {
    const at = common >= 0 ? common : s.data.findIndex((v) => v !== null && v !== 0);
    const base = at >= 0 ? s.data[at] : null;
    return {
      label: s.label,
      data: base
        ? s.data.map((v) => (v === null ? null : (v / base) * 100))
        : s.data.map(() => null),
    };
  });
  return { series: indexed, baseYear: common >= 0 ? labels[common] : null };
}

/** 実額と指数を切り替える。指数のときは軸のタイトルと書式も差し替える。 */
function trendChartArgs({ labels, series }, { axisTitle, axisTick, valueLabel }) {
  if (state.trendMode !== 'indexed') {
    return { labels, series, axisTitle, axisTick, valueLabel };
  }
  const { series: indexed, baseYear } = toIndexed(labels, series);
  return {
    labels,
    series: indexed,
    axisTitle: baseYear ? `${baseYear}年=100` : '最初の年=100',
    axisTick: (v) => fmt(v),
    valueLabel: (v) => fmt(v, 1),
  };
}

function setupTrendControls() {
  document.querySelectorAll('.trend-mode').forEach((select) => {
    [['absolute', '実額'], ['indexed', '変化（基準年=100）']].forEach(([value, label]) => {
      const option = el('option', null, label);
      option.value = value;
      select.append(option);
    });
    select.value = state.trendMode;
    select.addEventListener('change', () => {
      state.trendMode = select.value;
      // 2つのパネルで同じ状態を出しているので、もう一方も合わせる
      document.querySelectorAll('.trend-mode').forEach((other) => {
        other.value = state.trendMode;
      });
      if (state.lastTrendData) renderTrends(state.lastTrendData);
    });
  });
}

/** 選んだ市区町村の価格・人口の推移を、それぞれ1枚に重ねて描く。 */
function renderTrends(data) {
  state.lastTrendData = data;
  const items = data.map((item) => ({
    label: item.municipality.municipality_name,
    // 集計途中の年は件数が数分の一しかなく、末尾が急落したように見えるので除く
    price: (item.price_trend || []).filter((row) => !row.is_partial),
    stats: item.stats_trend || [],
  }));

  const price = (pick) => alignByYear(
    items.map((item) => ({ label: item.label, rows: item.price })), pick,
  );
  const stats = (pick) => alignByYear(
    items.map((item) => ({ label: item.label, rows: item.stats })), pick,
  );

  document.getElementById('trend-panel').hidden = false;
  renderLineChart('price', 'price-chart', trendChartArgs(
    price((row) => row?.land_unit_price),
    {
      axisTitle: '万円/㎡',
      axisTick: (v) => fmt(v / 10000, 1),
      valueLabel: (v) => `${fmt(v / 10000, 1)}万円/㎡`,
    },
  ));
  renderLineChart('priceHouse', 'price-house-chart', trendChartArgs(
    price((row) => row?.house_price),
    {
      axisTitle: '万円',
      axisTick: (v) => fmt(v / 10000),
      valueLabel: (v) => `${fmt(v / 10000)}万円`,
    },
  ));

  document.getElementById('pop-panel').hidden = false;
  renderLineChart('pop', 'pop-chart', trendChartArgs(
    stats((row) => row?.pop_total ?? row?.pop_census),
    {
      axisTitle: '万人',
      axisTick: (v) => fmt(v / 10000, 1),
      valueLabel: (v) => `${fmt(v)}人`,
    },
  ));
  renderLineChart('popYoung', 'pop-young-chart', trendChartArgs(
    stats((row) => row?.pop_0_14),
    {
      axisTitle: '万人',
      axisTick: (v) => fmt(v / 10000, 1),
      valueLabel: (v) => `${fmt(v)}人`,
    },
  ));
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
    ['医師密度（自市内）', fmt(metrics.doctors_per_10k, 1) + '人/万人', years.doctors],
    ['医師密度（15km圏）', fmt(metrics.doctors_catchment, 1) + '人/万人', '圏内で集計'],
    ['病院密度（15km圏）', fmt(metrics.hospitals_catchment, 2) + '施設/万人', '圏内で集計'],
    [
      '小児科密度（15km圏）',
      fmt(metrics.pediatric_clinics_catchment, 1) + '施設/子ども1万人',
      '圏内で集計',
    ],
    [
      '産科密度（15km圏）',
      fmt(metrics.obstetric_clinics_catchment, 2) + '施設/万人',
      '圏内で集計',
    ],
    [
      '15km圏内の自治体数',
      fmt(metrics.catchment_municipalities) + '自治体'
        + (metrics.catchment_missing
          ? `（うち${fmt(metrics.catchment_missing)}は統計未取得）` : ''),
      metrics.catchment_missing ? '県外を含むため過小の可能性' : '圏内すべて集計済み',
    ],
    ['診療所密度（自市内）', fmt(metrics.clinics_per_10k, 1) + '施設/万人', years.clinics],
    [
      '町内の駅数',
      fmt(metrics.station_count) + '駅',
      metrics.station_count ? '2023年度' : '鉄道駅なし',
    ],
    ['代表駅の乗降客数', fmt(metrics.station_passengers_max) + '人/日', '2023年度'],
    ['商業施設の密度', fmt(metrics.commerce_density, 0) + '所/km²', '2021年'],
    ['商業事業所数', fmt(metrics.commerce_shops) + '所', '2021年'],
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
        borderColor: seriesColor(index),
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 3,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        r: {
          min: 0,
          max: 100,
          // 既定の目盛りは明るい下地が付き、暗い面では白い箱に見えてしまう
          ticks: { stepSize: 25, backdropColor: 'transparent', font: { size: 10 } },
          pointLabels: { font: { size: 12 } },
        },
      },
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
  data.forEach((item, index) => {
    const code = item.municipality.municipality_code;
    const th = el('th', `num${code === state.focusCode ? ' is-focus' : ''}`);
    const button = el('button', 'link-button', item.municipality.municipality_name);
    button.title = '詳細をこの市区町村に切り替える';
    button.style.color = seriesColor(index);
    button.addEventListener('click', () => {
      state.focusCode = code;
      renderSelection();
      document.getElementById('detail-body').scrollIntoView({ behavior: 'smooth' });
    });
    th.append(button);
    headRow.append(th);
  });
  thead.append(headRow);

  const rows = [
    ['総合スコア', (item) => fmt(computeComposite(item.scores), 0), 'is-total'],
    ...state.meta.dimensions.map((dim) => [
      dim.key === 'affordability' && budgetActive() ? '予算適合' : dim.label,
      (item) => fmt(dimensionValue(item.scores, dim.key, budgetFit(item.scores)), 0),
    ]),
    // 総合点がどこで削られたかは、横並びで見るときにいちばん効く情報
    ['いちばん低い観点', (item) => {
      const detail = compositeDetail(item.scores);
      if (!detail || !detail.weakest) return '—';
      const dim = state.meta.dimensions.find((d) => d.key === detail.weakest.key);
      return `${dim ? dimensionLabel(dim) : detail.weakest.key} ${fmt(detail.weakest.value, 0)}`;
    }],
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

  rows.forEach(([label, accessor, rowClass]) => {
    const tr = el('tr', rowClass);
    tr.append(el('td', null, label));
    data.forEach((item) => {
      const code = item.municipality.municipality_code;
      tr.append(el('td', `num${code === state.focusCode ? ' is-focus' : ''}`, accessor(item)));
    });
    tbody.append(tr);
  });
}

// ---------------------------------------------------------------- ローン試算
//
// 元利均等返済 … 毎回の返済額が一定。月利 r、回数 n、借入 P として
//                  返済額 = P·r ÷ (1 − (1+r)^−n)
// 元金均等返済 … 毎回の元金が P/n で一定。利息はその時点の残高に掛かるので、
//                  返済額は初回が最大で年々下がる。
//
// 金利0%のときは (1+r)^−n が1になって分母が0になるため、別扱いにする。

function buildSchedule({ principal, annualRate, years, method }) {
  const n = Math.round(years * 12);
  if (!(principal > 0) || !(n > 0)) return null;

  const r = annualRate / 100 / 12;
  const rows = [];
  let balance = principal;
  let totalInterest = 0;

  const flatPayment = r === 0
    ? principal / n
    : (principal * r) / (1 - Math.pow(1 + r, -n));
  const flatPrincipal = principal / n;

  for (let i = 1; i <= n; i += 1) {
    const interest = balance * r;
    let principalPart;
    let payment;

    if (method === 'equal_principal') {
      principalPart = flatPrincipal;
      payment = principalPart + interest;
    } else {
      payment = flatPayment;
      principalPart = payment - interest;
    }

    // 端数の積み上がりで最終回に残高が残らないよう、最後は残高で締める
    if (i === n) {
      principalPart = balance;
      payment = principalPart + interest;
    }

    balance = Math.max(0, balance - principalPart);
    totalInterest += interest;
    rows.push({ month: i, payment, interest, principal: principalPart, balance });
  }

  return {
    months: rows,
    totalInterest,
    totalPayment: principal + totalInterest,
    firstPayment: rows[0].payment,
    lastPayment: rows[rows.length - 1].payment,
    isFlat: method !== 'equal_principal',
  };
}

function yearlySchedule(schedule) {
  const years = [];
  schedule.months.forEach((row, index) => {
    const year = Math.floor(index / 12);
    if (!years[year]) {
      years[year] = { year: year + 1, payment: 0, interest: 0, principal: 0, balance: 0 };
    }
    years[year].payment += row.payment;
    years[year].interest += row.interest;
    years[year].principal += row.principal;
    years[year].balance = row.balance;
  });
  return years;
}

function loanInputs() {
  const model = state.meta?.loan_model ?? {};
  const price = Number(document.getElementById('loan-price').value || 0);
  const down = Number(document.getElementById('loan-down').value || 0);
  return {
    price,
    down,
    // 頭金が価格を上回っても借入がマイナスにならないようにする
    principal: Math.max(0, (price - down)) * 10000,
    annualRate: Number(document.getElementById('loan-rate').value || 0),
    years: Number(document.getElementById('loan-years').value || model.loan_years || 35),
    method: document.getElementById('loan-method').value || 'equal_payment',
    ratio: Number(document.getElementById('loan-ratio').value || 25),
  };
}

function setupLoanView() {
  const model = state.meta?.loan_model;
  if (!model) return;

  const yearSelect = document.getElementById('loan-years');
  (model.loan_years_options ?? [35]).forEach((years) => {
    const option = el('option', null, `${years}年`);
    option.value = String(years);
    yearSelect.append(option);
  });

  const methodSelect = document.getElementById('loan-method');
  (model.methods ?? []).forEach((method) => {
    const option = el('option', null, method.label);
    option.value = method.key;
    methodSelect.append(option);
  });

  const ratioSelect = document.getElementById('loan-ratio');
  (model.repayment_ratios ?? [25]).forEach((ratio) => {
    const option = el('option', null, `${ratio}%`);
    option.value = String(ratio);
    ratioSelect.append(option);
  });

  const excludes = document.getElementById('loan-excludes');
  (model.excludes ?? []).forEach((item) => excludes.append(el('li', null, item)));

  applyLoanDefaults();
  document.getElementById('loan-reset').addEventListener('click', () => {
    applyLoanDefaults();
    renderLoan();
  });
  document.getElementById('loan-form').addEventListener('input', renderLoan);
  document.getElementById('loan-form').addEventListener('change', renderLoan);
  renderLoan();
}

function applyLoanDefaults() {
  const model = state.meta.loan_model;
  document.getElementById('loan-price').value = model.price;
  document.getElementById('loan-down').value = model.down_payment;
  document.getElementById('loan-rate').value = model.interest_rate;
  document.getElementById('loan-years').value = String(model.loan_years);
  document.getElementById('loan-method').value = model.method;
  document.getElementById('loan-ratio').value = String(model.default_repayment_ratio);
}

function renderLoan() {
  const input = loanInputs();
  const schedule = buildSchedule(input);

  const methodMeta = (state.meta.loan_model.methods ?? [])
    .find((m) => m.key === input.method);
  document.getElementById('loan-method-note').textContent =
    methodMeta ? methodMeta.description : '';

  const monthlyEl = document.getElementById('loan-monthly');
  const labelEl = document.getElementById('loan-monthly-label');
  const subEl = document.getElementById('loan-monthly-sub');
  const summaryEl = document.getElementById('loan-summary');
  const incomeEl = document.getElementById('loan-income');
  const tbody = document.querySelector('#loan-table tbody');

  summaryEl.innerHTML = '';
  incomeEl.innerHTML = '';
  tbody.innerHTML = '';

  if (!schedule) {
    labelEl.textContent = '毎月の返済額';
    monthlyEl.textContent = '—';
    subEl.textContent = '物件価格と頭金を入力してください。';
    destroyChart('loan');
    return;
  }

  if (schedule.isFlat) {
    labelEl.textContent = '毎月の返済額';
    monthlyEl.textContent = `${fmt(schedule.firstPayment)}円`;
    subEl.textContent = `${input.years}年間ずっと同じ金額です`;
  } else {
    labelEl.textContent = '毎月の返済額（初回）';
    monthlyEl.textContent = `${fmt(schedule.firstPayment)}円`;
    subEl.textContent =
      `最終回は ${fmt(schedule.lastPayment)}円 まで下がります`;
  }

  const summaryItems = [
    ['借入額', `${fmt(input.principal)}円`],
    ['利息の総額', `${fmt(schedule.totalInterest)}円`],
    ['総返済額', `${fmt(schedule.totalPayment)}円`],
    ['頭金を含めた総支払', `${fmt(schedule.totalPayment + input.down * 10000)}円`],
  ];
  summaryItems.forEach(([label, value]) => {
    const card = el('div', 'loan-stat');
    card.append(el('span', 'loan-stat-label', label));
    card.append(el('span', 'loan-stat-value', value));
    summaryEl.append(card);
  });

  // 年収の目安。元金均等は返済額が下がるので、いちばん重い初年度で見る。
  const firstYearPayment = schedule.months
    .slice(0, 12)
    .reduce((total, row) => total + row.payment, 0);
  (state.meta.loan_model.repayment_ratios ?? [25]).forEach((ratio) => {
    const income = firstYearPayment / (ratio / 100);
    const card = el('div', `income-card${ratio === input.ratio ? ' is-active' : ''}`);
    card.append(el('span', 'income-ratio', `返済負担率 ${ratio}%`));
    card.append(el('span', 'income-value', `${fmt(income / 10000)}万円`));
    card.append(el('span', 'income-note',
      ratio <= 20 ? '余裕を持ちたい場合'
        : ratio >= 30 ? '審査上の上限に近い水準' : '一般的な目安'));
    incomeEl.append(card);
  });

  const years = yearlySchedule(schedule);
  years.forEach((row) => {
    const tr = el('tr');
    tr.append(el('td', null, `${row.year}年目`));
    tr.append(el('td', 'num', fmt(row.payment)));
    tr.append(el('td', 'num', fmt(row.principal)));
    tr.append(el('td', 'num', fmt(row.interest)));
    tr.append(el('td', 'num', fmt(row.balance)));
    tbody.append(tr);
  });

  renderLoanChart(years);
}

function renderLoanChart(years) {
  destroyChart('loan');
  const canvas = document.getElementById('loan-chart');
  const ink = cssVar('--chart-ink');
  const grid = cssVar('--chart-grid');

  state.charts.loan = new Chart(canvas, {
    data: {
      labels: years.map((y) => `${y.year}年目`),
      datasets: [
        {
          type: 'bar',
          label: '元金',
          data: years.map((y) => Math.round(y.principal)),
          backgroundColor: cssVar('--series-1'),
          stack: 'payment',
          yAxisID: 'y',
        },
        {
          type: 'bar',
          label: '利息',
          data: years.map((y) => Math.round(y.interest)),
          backgroundColor: cssVar('--series-2'),
          stack: 'payment',
          yAxisID: 'y',
        },
        {
          type: 'line',
          label: '残高',
          data: years.map((y) => Math.round(y.balance)),
          borderColor: cssVar('--series-3'),
          backgroundColor: 'transparent',
          yAxisID: 'y1',
          tension: 0.2,
          pointRadius: 0,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: ink } },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${fmt(ctx.parsed.y)}円`,
          },
        },
      },
      scales: {
        x: { stacked: true, ticks: { color: ink, maxTicksLimit: 12 }, grid: { color: grid } },
        y: {
          stacked: true,
          position: 'left',
          title: { display: true, text: '年間返済額', color: ink },
          ticks: { color: ink, callback: (v) => `${(v / 10000).toFixed(0)}万` },
          grid: { color: grid },
        },
        y1: {
          position: 'right',
          title: { display: true, text: '残高', color: ink },
          ticks: { color: ink, callback: (v) => `${(v / 10000000).toFixed(1)}千万` },
          grid: { drawOnChartArea: false },
        },
      },
    },
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
