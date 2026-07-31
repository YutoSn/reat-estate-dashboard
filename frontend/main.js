import Chart from 'chart.js/auto';

// グローバル変数
let priceChartInstance = null;
let popChartInstance = null;
let selectedAreas = []; // { id, city_code, district_name, marker }
let map = null;
let markerLayer = null;
let mlitTileLayer = null;
let scoreRadarChartInstance = null;
let scoreTrendChartInstance = null;

const COLORS = [
    { border: '#3b82f6', bg: 'rgba(59, 130, 246, 0.1)' },
    { border: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)' },
    { border: '#10b981', bg: 'rgba(16, 185, 129, 0.1)' },
    { border: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)' },
    { border: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.1)' },
    { border: '#ec4899', bg: 'rgba(236, 72, 153, 0.1)' },
    { border: '#06b6d4', bg: 'rgba(6, 182, 212, 0.1)' },
    { border: '#84cc16', bg: 'rgba(132, 204, 22, 0.1)' },
    { border: '#f97316', bg: 'rgba(249, 115, 22, 0.1)' },
    { border: '#64748b', bg: 'rgba(100, 116, 139, 0.1)' }
];

// 初期化
function init() {
    initMap();
    initDropdowns(); // ドロップダウンの初期化
    updateCharts(); // 空のグラフを描画

    document.getElementById('reset-btn').addEventListener('click', clearAll);
    
    // ドロップダウンのイベントリスナー
    document.getElementById('pref-select').addEventListener('change', onPrefChange);
    document.getElementById('city-select').addEventListener('change', onCityChange);
    document.getElementById('district-select').addEventListener('change', onDistrictChange);
    document.getElementById('add-area-btn').addEventListener('click', onAddAreaClick);
}

// ドロップダウン関連の関数
async function initDropdowns() {
    try {
        const res = await fetch('/api/prefectures');
        const prefectures = await res.json();
        const prefSelect = document.getElementById('pref-select');
        prefectures.forEach(pref => {
            const option = document.createElement('option');
            option.value = pref.code;
            option.textContent = pref.name;
            prefSelect.appendChild(option);
        });
    } catch (err) {
        console.error("都道府県の取得に失敗しました", err);
    }
}

async function onPrefChange(e) {
    const prefCode = e.target.value;
    const citySelect = document.getElementById('city-select');
    const districtSelect = document.getElementById('district-select');
    const addBtn = document.getElementById('add-area-btn');
    
    citySelect.innerHTML = '<option value="">市区町村を選択</option>';
    districtSelect.innerHTML = '<option value="">エリアを選択</option>';
    citySelect.disabled = true;
    districtSelect.disabled = true;
    addBtn.disabled = true;

    if (!prefCode) return;

    try {
        const res = await fetch(`/api/cities/${prefCode}`);
        const cities = await res.json();
        cities.forEach(city => {
            const option = document.createElement('option');
            option.value = city.municipality_code;
            option.textContent = city.municipality;
            citySelect.appendChild(option);
        });
        citySelect.disabled = false;
    } catch (err) {
        console.error("市区町村の取得に失敗しました", err);
    }
}

async function onCityChange(e) {
    const cityCode = e.target.value;
    const districtSelect = document.getElementById('district-select');
    const addBtn = document.getElementById('add-area-btn');
    
    districtSelect.innerHTML = '<option value="">エリアを選択</option>';
    districtSelect.disabled = true;
    addBtn.disabled = true;

    if (!cityCode) return;

    try {
        const res = await fetch(`/api/districts/${cityCode}`);
        const districts = await res.json();
        districts.forEach(district => {
            const option = document.createElement('option');
            option.value = district;
            option.textContent = district;
            districtSelect.appendChild(option);
        });
        districtSelect.disabled = false;
    } catch (err) {
        console.error("エリアの取得に失敗しました", err);
    }
}

function onDistrictChange(e) {
    const addBtn = document.getElementById('add-area-btn');
    addBtn.disabled = !e.target.value;
}

async function onAddAreaClick() {
    const prefSelect = document.getElementById('pref-select');
    const citySelect = document.getElementById('city-select');
    const districtSelect = document.getElementById('district-select');
    
    const prefName = prefSelect.options[prefSelect.selectedIndex].text;
    const cityCode = citySelect.value;
    const cityName = citySelect.options[citySelect.selectedIndex].text;
    const districtName = districtSelect.value;
    
    if (!cityCode || !districtName) return;

    const areaId = cityCode + '_' + districtName;
    if (selectedAreas.some(a => a.id === areaId)) {
        alert('このエリアはすでに追加されています。');
        return;
    }

    if (selectedAreas.length >= 10) {
        alert('比較できるエリアは最大10個までです。');
        return;
    }
    
    // UIをロード中にする
    const addBtn = document.getElementById('add-area-btn');
    addBtn.disabled = true;
    addBtn.textContent = '追加中...';

    try {
        // 1. Nominatim APIで緯度経度を取得 (例: "東京都 渋谷区 渋谷１丁目")
        const query = `${prefName} ${cityName} ${districtName}`;
        const geocodeUrl = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}`;
        
        let latlng = null;
        try {
            const geoRes = await fetch(geocodeUrl);
            const geoData = await geoRes.json();
            if (geoData && geoData.length > 0) {
                latlng = L.latLng(geoData[0].lat, geoData[0].lon);
            }
        } catch(geoErr) {
            console.warn("ジオコーディングに失敗しました", geoErr);
        }

        // もし詳細な町丁名で見つからなければ、市区町村名だけで再検索して近似値を出す
        if (!latlng) {
            const fallbackQuery = `${prefName} ${cityName}`;
            const fallbackUrl = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(fallbackQuery)}`;
            try {
                const fbRes = await fetch(fallbackUrl);
                const fbData = await fbRes.json();
                if (fbData && fbData.length > 0) {
                    latlng = L.latLng(fbData[0].lat, fbData[0].lon);
                    console.info("市区町村レベルでの座標にフォールバックしました:", latlng);
                }
            } catch(fbErr) {
                console.warn("フォールバックジオコーディングにも失敗しました", fbErr);
            }
        }

        // 2. トレンドデータを取得
        const trendRes = await fetch(`/api/trend?city_code=${cityCode}&district_name=${encodeURIComponent(districtName)}`);
        if (!trendRes.ok) throw new Error('API Error');
        const data = await trendRes.json();
        
        if (data.trend.every(d => d.avg_price_per_sqm === null)) {
            alert(`${districtName} の地価データは見つかりませんでした（人口推移のみ表示されます）。データが存在しないか、取引実績がないエリアです。`);
        }
        
        let marker = null;
        if (latlng) {
            const icon = L.divIcon({
                className: 'custom-div-icon',
                html: `<div style='font-size: 24px; color: gold; text-shadow: 0 0 5px black;'>⭐</div>`,
                iconSize: [30, 30],
                iconAnchor: [15, 15]
            });
            marker = L.marker(latlng, { icon }).addTo(markerLayer);
            map.flyTo(latlng, 14); // 追加した場所にズーム
        }

        selectedAreas.push({
            id: areaId,
            city_code: cityCode,
            pref_name: prefName,
            city_name: cityName,
            district_name: districtName,
            trend: data.trend,
            marker: marker
        });

        updateCharts();
    } catch (err) {
        console.error("エリアの追加に失敗:", err);
        alert("データの取得に失敗しました。");
    } finally {
        addBtn.disabled = false;
        addBtn.textContent = '追加';
    }
}


function initMap() {
    // 東京駅付近を初期中心に
    map = L.map('interactive-map').setView([35.6812, 139.7671], 13);
    
    // ベースマップ (CartoDB Dark Matter for dark mode)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO'
    }).addTo(map);

    // スターピンを置くためのレイヤー
    markerLayer = L.layerGroup().addTo(map);

    // 国交省 XPT001 API (成約価格等タイル) レイヤー
    mlitTileLayer = L.vectorGrid.protobuf('/api/tiles/{z}/{x}/{y}', {
        vectorTileLayerStyles: {
            xpt001: {
                fill: true,
                weight: 1,
                fillColor: '#ec4899',
                color: '#ec4899',
                fillOpacity: 0.5,
                opacity: 0.8,
                radius: 5
            },
            XPT001: {
                fill: true,
                weight: 1,
                fillColor: '#ec4899',
                color: '#ec4899',
                fillOpacity: 0.5,
                opacity: 0.8,
                radius: 5
            }
        },
        interactive: true,
        getFeatureId: function(f) {
            return f.properties.id || Math.random();
        }
    });

    mlitTileLayer.on('click', function(e) {
        if(e.layer.properties) {
            const props = e.layer.properties;
            // 重要なプロパティを先頭に表示
            const importantKeys = ['TradePrice', 'PricePerUnit', 'Area', 'Municipality', 'DistrictName', 'Type', 'Period'];
            let content = '<div style="margin-bottom: 8px; font-weight: bold; border-bottom: 1px solid #ccc; padding-bottom: 4px;">取引情報</div>';
            
            importantKeys.forEach(k => {
                if (props[k]) {
                    content += `<b>${k}</b>: ${props[k]}<br>`;
                }
            });
            
            content += '<details style="margin-top: 8px;"><summary style="cursor:pointer; color:#0366d6;">すべてのプロパティを表示</summary><div style="margin-top: 4px;">';
            Object.keys(props).forEach(k => {
                if (!importantKeys.includes(k)) {
                    content += `<b>${k}</b>: ${props[k]}<br>`;
                }
            });
            content += '</div></details>';

            L.popup()
             .setContent(`<div style="max-height: 250px; overflow-y: auto; font-size: 13px; line-height: 1.4;">${content}</div>`)
             .setLatLng(e.latlng)
             .openOn(map);
        }
    });

    const toggleMlit = document.getElementById('toggle-mlit-tiles');
    if (toggleMlit) {
        toggleMlit.addEventListener('change', (e) => {
            if (e.target.checked) {
                mlitTileLayer.addTo(map);
            } else {
                map.removeLayer(mlitTileLayer);
            }
        });
    }
}

function removeArea(id) {
    const idx = selectedAreas.findIndex(a => a.id === id);
    if (idx !== -1) {
        const area = selectedAreas[idx];
        if (area.marker) {
            markerLayer.removeLayer(area.marker);
        }
        selectedAreas.splice(idx, 1);
        updateCharts();
    }
}

function clearAll() {
    selectedAreas.forEach(area => {
        if (area.marker) {
            markerLayer.removeLayer(area.marker);
        }
    });
    selectedAreas = [];
    updateCharts();
}

// グラフの更新
function updateCharts() {
    const currentYear = new Date().getFullYear();
    const startYear = currentYear - 20;
    const labels = [];
    for(let y = startYear + 1; y <= currentYear; y++) {
        labels.push(`${y}年`);
    }

    const priceDatasets = [];
    const popDatasets = [];
    const radarDatasets = [];
    const scoreTrendDatasets = [];

    selectedAreas.forEach((area, index) => {
        const color = COLORS[index % COLORS.length];
        const prices = [];
        const pops = [];
        const overallScores = [];

        // 最新の有効なレコードを取得
        let latestRecord = area.trend.slice().reverse().find(d => d.population > 0);
        if (!latestRecord && area.trend.length > 0) {
            latestRecord = area.trend[area.trend.length - 1];
        }

        // 年齢別人口データ（詳細データ）を持つ最新のレコードを取得 (例: 2020年の国勢調査)
        let latestDetailedPopRecord = area.trend.slice().reverse().find(d => d.pop_0_14 != null && d.population > 0) || latestRecord;

        // 地価・取引データを持つ最新のレコードを取得
        let latestPriceRecord = area.trend.slice().reverse().find(d => d.avg_price_per_sqm > 0) || latestRecord;

        let convenienceScore = 0;
        let childcareScore = 0;
        let futureScore = 0;
        
        if (latestPriceRecord) {
            const price = latestPriceRecord.avg_price_per_sqm || 0;
            const txCount = latestPriceRecord.transaction_count || 0;
            // 利便性スコア (地価と取引件数から算出、Max100) は最新の地価を使用
            convenienceScore = Math.min(100, Math.round(((price / 1000000) * 60) + Math.min(40, txCount * 1.5)));
        }

        if (latestDetailedPopRecord) {
            const pop = latestDetailedPopRecord.population || 1;
            const pop0_14 = latestDetailedPopRecord.pop_0_14 || 0;
            const pop15_64 = latestDetailedPopRecord.pop_15_64 || 0;

            // 子育てスコア (15%を基準100とする)
            childcareScore = Math.min(100, Math.round((pop0_14 / pop) * (100 / 0.15)));
            // 将来性スコア (65%を基準100とする)
            futureScore = Math.min(100, Math.round((pop15_64 / pop) * (100 / 0.65)));
        }

        // 推移用の年齢割合（データがない年は直近の割合を引き継ぐ）
        let firstDetailedPopRecord = area.trend.find(d => d.pop_0_14 != null && d.population > 0);
        let lastPop0_14Ratio = firstDetailedPopRecord ? (firstDetailedPopRecord.pop_0_14 / firstDetailedPopRecord.population) : 0;
        let lastPop15_64Ratio = firstDetailedPopRecord ? (firstDetailedPopRecord.pop_15_64 / firstDetailedPopRecord.population) : 0;

        // 推移用の地価データ（データがない年は直近の地価を引き継ぐ）
        let firstPriceRecord = area.trend.find(d => d.avg_price_per_sqm > 0);
        let lastPrice = firstPriceRecord ? firstPriceRecord.avg_price_per_sqm : 0;
        let lastTx = firstPriceRecord ? firstPriceRecord.transaction_count : 0;

        for(let y = startYear + 1; y <= currentYear; y++) {
            const record = area.trend.find(d => d.year === y);
            prices.push(record ? record.avg_price_per_sqm : null);
            pops.push(record ? record.population : null);

            // 推移用の総合スコア計算
            if (record && record.population) {
                const pop = record.population;
                
                if (record.pop_0_14 != null) {
                    lastPop0_14Ratio = record.pop_0_14 / pop;
                    lastPop15_64Ratio = record.pop_15_64 / pop;
                }
                
                if (record.avg_price_per_sqm != null) {
                    lastPrice = record.avg_price_per_sqm;
                    lastTx = record.transaction_count;
                }
                
                let cScore = Math.min(100, (lastPop0_14Ratio * (100 / 0.15)));
                let fScore = Math.min(100, (lastPop15_64Ratio * (100 / 0.65)));
                let cvScore = Math.min(100, ((lastPrice / 1000000) * 60) + Math.min(40, lastTx * 1.5));
                
                overallScores.push(Math.round((cScore + fScore + cvScore) / 3));
            } else {
                overallScores.push(null);
            }
        }

        const labelName = `${area.district_name}`; // (市区町村単位の場合は city_name も入れるが、APIからはdistrict_nameのみ)

        priceDatasets.push({
            label: labelName,
            data: prices,
            borderColor: color.border,
            backgroundColor: color.bg,
            borderWidth: 2,
            tension: 0.3,
            fill: false,
            spanGaps: true,
            pointBackgroundColor: color.border,
            pointRadius: 3
        });

        popDatasets.push({
            label: labelName, // 人口は市区町村単位
            data: pops,
            borderColor: color.border,
            backgroundColor: color.border,
            borderWidth: 2,
            tension: 0.3,
            fill: false,
            spanGaps: true,
            pointBackgroundColor: color.border,
            pointRadius: 3
        });

        if (latestRecord) {
            radarDatasets.push({
                label: labelName,
                data: [convenienceScore, childcareScore, futureScore],
                borderColor: color.border,
                backgroundColor: color.bg,
                pointBackgroundColor: color.border,
                borderWidth: 2
            });
        }

        scoreTrendDatasets.push({
            label: labelName,
            data: overallScores,
            borderColor: color.border,
            backgroundColor: color.bg,
            borderWidth: 2,
            tension: 0.3,
            fill: false,
            spanGaps: true,
            pointBackgroundColor: color.border,
            pointRadius: 3
        });
    });

    // --- 地価推移チャート ---
    const ctxPrice = document.getElementById('priceChart').getContext('2d');
    if (priceChartInstance) priceChartInstance.destroy();
    
    priceChartInstance = new Chart(ctxPrice, {
        type: 'line',
        data: { labels: labels, datasets: priceDatasets },
        options: getChartOptions('平米単価')
    });

    // --- 人口推移チャート ---
    const ctxPop = document.getElementById('popChart').getContext('2d');
    if (popChartInstance) popChartInstance.destroy();
    
    popChartInstance = new Chart(ctxPop, {
        type: 'line',
        data: { labels: labels, datasets: popDatasets },
        options: getChartOptions('人口')
    });

    // --- レーダーチャート (総合特性スコア) ---
    const ctxRadar = document.getElementById('scoreRadarChart');
    if (ctxRadar) {
        if (scoreRadarChartInstance) scoreRadarChartInstance.destroy();
        scoreRadarChartInstance = new Chart(ctxRadar.getContext('2d'), {
            type: 'radar',
            data: {
                labels: ['生活利便性・交通', '子育て・教育環境', '将来性・住民特性'],
                datasets: radarDatasets
            },
            options: getRadarChartOptions()
        });
    }

    // --- 総合スコア推移チャート ---
    const ctxScoreTrend = document.getElementById('scoreTrendChart');
    if (ctxScoreTrend) {
        if (scoreTrendChartInstance) scoreTrendChartInstance.destroy();
        scoreTrendChartInstance = new Chart(ctxScoreTrend.getContext('2d'), {
            type: 'line',
            data: { labels: labels, datasets: scoreTrendDatasets },
            options: getChartOptions('総合スコア')
        });
    }

    // --- 選択エリアのリスト表示の更新 ---
    renderSelectedAreasList();
}

function renderSelectedAreasList() {
    const listContainer = document.getElementById('selected-areas-list');
    listContainer.innerHTML = ''; // クリア

    selectedAreas.forEach((area, index) => {
        const color = COLORS[index % COLORS.length];

        const item = document.createElement('div');
        item.className = 'selected-area-item';

        const indicator = document.createElement('span');
        indicator.className = 'selected-area-color-indicator';
        indicator.style.backgroundColor = color.border;

        const text = document.createElement('span');
        text.textContent = `${area.pref_name} ${area.city_name} ${area.district_name}`;

        const removeBtn = document.createElement('button');
        removeBtn.className = 'remove-area-btn';
        removeBtn.innerHTML = '✕';
        removeBtn.title = '削除';
        removeBtn.onclick = () => {
            removeArea(area.id);
        };

        item.appendChild(indicator);
        item.appendChild(text);
        item.appendChild(removeBtn);

        listContainer.appendChild(item);
    });
}

// 共通チャートオプション
function getChartOptions(yLabel) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        color: '#94a3b8',
        interaction: {
            mode: 'index',
            intersect: false,
        },
        scales: {
            y: {
                beginAtZero: false,
                grid: { color: 'rgba(255, 255, 255, 0.05)' },
                ticks: { color: '#94a3b8' }
            },
            x: {
                grid: { display: false },
                ticks: { color: '#94a3b8' }
            }
        },
        plugins: {
            legend: {
                position: 'bottom',
                labels: { color: '#f8fafc', usePointStyle: true, padding: 15 }
            },
            tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.9)',
                titleColor: '#fff',
                bodyColor: '#cbd5e1',
                borderColor: 'rgba(255,255,255,0.1)',
                borderWidth: 1
            }
        }
    };
}

function getRadarChartOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        color: '#94a3b8',
        scales: {
            r: {
                angleLines: { color: 'rgba(255, 255, 255, 0.1)' },
                grid: { color: 'rgba(255, 255, 255, 0.1)' },
                pointLabels: { color: '#f8fafc', font: { size: 13 } },
                ticks: {
                    color: '#94a3b8',
                    backdropColor: 'transparent',
                    min: 0,
                    max: 100,
                    stepSize: 20,
                    display: false
                }
            }
        },
        plugins: {
            legend: {
                position: 'bottom',
                labels: { color: '#f8fafc', usePointStyle: true, padding: 15 }
            },
            tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.9)',
                titleColor: '#fff',
                bodyColor: '#cbd5e1',
                borderColor: 'rgba(255,255,255,0.1)',
                borderWidth: 1
            }
        }
    };
}

// 実行
init();
