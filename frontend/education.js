document.addEventListener('DOMContentLoaded', () => {
    // 1. 都道府県リストをハードコードまたはAPIから取得
    const prefs = [
        {code: '11', name: '埼玉県'},
        {code: '12', name: '千葉県'},
        {code: '13', name: '東京都'},
        {code: '14', name: '神奈川県'}
    ];
    
    const prefSelect = document.getElementById('pref-select');
    const citySelect = document.getElementById('city-select');
    const dashboard = document.getElementById('education-dashboard');
    const cityTitle = document.getElementById('selected-city-title');
    
    // チャートインスタンス
    let radarChart, nurseryChart, schoolChart, medicalChart, popChart;

    prefs.forEach(p => {
        const option = document.createElement('option');
        option.value = p.code;
        option.textContent = p.name;
        prefSelect.appendChild(option);
    });

    prefSelect.addEventListener('change', async (e) => {
        const prefCode = e.target.value;
        citySelect.innerHTML = '<option value="">選択してください</option>';
        citySelect.disabled = true;
        dashboard.style.display = 'none';
        cityTitle.textContent = '市区町村を選択してください';
        
        if (!prefCode) return;

        try {
            const res = await fetch(`/api/cities?pref_code=${prefCode}`);
            const cities = await res.json();
            
            cities.forEach(city => {
                const option = document.createElement('option');
                option.value = city.municipality_code;
                option.textContent = city.municipality;
                citySelect.appendChild(option);
            });
            citySelect.disabled = false;
        } catch (error) {
            console.error('Error fetching cities:', error);
        }
    });

    citySelect.addEventListener('change', async (e) => {
        const cityCode = e.target.value;
        const cityName = e.target.options[e.target.selectedIndex].text;
        
        if (!cityCode) {
            dashboard.style.display = 'none';
            cityTitle.textContent = '市区町村を選択してください';
            return;
        }

        cityTitle.textContent = cityName + ' の教育・子育て分析';
        dashboard.style.display = 'block';
        await loadEducationData(cityCode);
    });

    async function loadEducationData(cityCode) {
        try {
            const res = await fetch(`/api/education_trend?city_code=${cityCode}`);
            const data = await res.json();
            const trend = data.trend;
            
            if (!trend || trend.length === 0) {
                alert('データが見つかりませんでした。');
                return;
            }

            // 最新年のデータを取得 (降順ソートされていると仮定、または末尾)
            const sortedTrend = [...trend].sort((a, b) => b.year - a.year);
            const latest = sortedTrend[0];
            
            renderRadarChart(latest);
            renderTrendCharts(sortedTrend.reverse()); // 昇順に戻す
        } catch (error) {
            console.error('Error fetching education trend:', error);
        }
    }

    function calculateScore(value, population, baselinePer10k) {
        if (!value || !population) return 0;
        // 人口1万人あたりの数
        const per10k = (value / population) * 10000;
        // ベースラインに対する割合をスコア化 (Max 100)
        let score = (per10k / baselinePer10k) * 50;
        return Math.min(Math.max(Math.round(score), 0), 100);
    }

    function renderRadarChart(latest) {
        const pop = latest.population;
        
        // スコア計算 (適当なベースラインを設定)
        const nurseryScore = calculateScore(latest.nurseries, pop, 2.0); // 1万人に2つを偏差値50
        const schoolScore = calculateScore(latest.elementary_schools + latest.junior_high_schools, pop, 3.0);
        const medicalScore = calculateScore(latest.pediatricians, pop, 10.0); // 1万人に10人を偏差値50
        const libraryScore = calculateScore(latest.libraries, pop, 0.5);
        
        // 0-14歳比率スコア
        const childRatio = latest.pop_0_14 && pop ? (latest.pop_0_14 / pop) * 100 : 0;
        const childScore = Math.min(Math.round((childRatio / 15.0) * 50), 100);

        const detailsHtml = `
            <div style="background: #f8fafc; padding: 16px; border-radius: 8px;">
                <h4 style="margin-bottom: 12px; color: #334155; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px;">指標内訳（直近データ）</h4>
                <ul style="list-style: none; padding: 0; margin: 0; line-height: 1.8;">
                    <li><span style="display:inline-block; width:120px; color:#64748b;">保育所等数:</span> <strong>${latest.nurseries || '-'}</strong> カ所 <span style="font-size:0.85em; color:#94a3b8;">(スコア: ${nurseryScore})</span></li>
                    <li><span style="display:inline-block; width:120px; color:#64748b;">小中学校数:</span> <strong>${(latest.elementary_schools||0) + (latest.junior_high_schools||0)}</strong> 校 <span style="font-size:0.85em; color:#94a3b8;">(スコア: ${schoolScore})</span></li>
                    <li><span style="display:inline-block; width:120px; color:#64748b;">小児科医師数:</span> <strong>${latest.pediatricians || '-'}</strong> 人 <span style="font-size:0.85em; color:#94a3b8;">(スコア: ${medicalScore})</span></li>
                    <li><span style="display:inline-block; width:120px; color:#64748b;">公共図書館数:</span> <strong>${latest.libraries || '-'}</strong> カ所 <span style="font-size:0.85em; color:#94a3b8;">(スコア: ${libraryScore})</span></li>
                    <li><span style="display:inline-block; width:120px; color:#64748b;">0-14歳人口比率:</span> <strong>${childRatio.toFixed(1)}</strong> % <span style="font-size:0.85em; color:#94a3b8;">(スコア: ${childScore})</span></li>
                </ul>
            </div>
        `;
        document.getElementById('score-details').innerHTML = detailsHtml;

        const ctx = document.getElementById('scoreRadarChart').getContext('2d');
        if (radarChart) radarChart.destroy();
        
        radarChart = new Chart(ctx, {
            type: 'radar',
            data: {
                labels: ['保育環境', '学校インフラ', '小児医療', '文化施設', '子供の多さ'],
                datasets: [{
                    label: 'インフラスコア',
                    data: [nurseryScore, schoolScore, medicalScore, libraryScore, childScore],
                    backgroundColor: 'rgba(59, 130, 246, 0.2)',
                    borderColor: 'rgba(59, 130, 246, 1)',
                    pointBackgroundColor: 'rgba(59, 130, 246, 1)',
                    pointBorderColor: '#fff',
                    pointHoverBackgroundColor: '#fff',
                    pointHoverBorderColor: 'rgba(59, 130, 246, 1)'
                }]
            },
            options: {
                scales: {
                    r: {
                        angleLines: { color: 'rgba(0, 0, 0, 0.1)' },
                        grid: { color: 'rgba(0, 0, 0, 0.1)' },
                        pointLabels: {
                            font: { family: "'Inter', sans-serif", size: 12 },
                            color: '#475569'
                        },
                        ticks: {
                            min: 0,
                            max: 100,
                            stepSize: 20,
                            backdropColor: 'transparent',
                            color: '#94a3b8'
                        }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }

    function renderTrendCharts(trend) {
        const years = trend.map(t => t.year);
        
        // 1万人あたりの計算関数
        const per10k = (val, pop) => (val && pop) ? (val / pop) * 10000 : null;

        // 保育・幼稚園
        if (nurseryChart) nurseryChart.destroy();
        nurseryChart = new Chart(document.getElementById('nurseryTrendChart').getContext('2d'), {
            type: 'line',
            data: {
                labels: years,
                datasets: [
                    { label: '保育所等', data: trend.map(t => per10k(t.nurseries, t.population)), borderColor: '#f59e0b', tension: 0.1 },
                    { label: '幼稚園', data: trend.map(t => per10k(t.kindergartens, t.population)), borderColor: '#10b981', tension: 0.1 }
                ]
            }
        });

        // 学校
        if (schoolChart) schoolChart.destroy();
        schoolChart = new Chart(document.getElementById('schoolTrendChart').getContext('2d'), {
            type: 'line',
            data: {
                labels: years,
                datasets: [
                    { label: '小学校', data: trend.map(t => per10k(t.elementary_schools, t.population)), borderColor: '#3b82f6', tension: 0.1 },
                    { label: '中学校', data: trend.map(t => per10k(t.junior_high_schools, t.population)), borderColor: '#6366f1', tension: 0.1 }
                ]
            }
        });

        // 医療
        if (medicalChart) medicalChart.destroy();
        medicalChart = new Chart(document.getElementById('medicalTrendChart').getContext('2d'), {
            type: 'line',
            data: {
                labels: years,
                datasets: [
                    { label: '小児科医師数', data: trend.map(t => per10k(t.pediatricians, t.population)), borderColor: '#ef4444', tension: 0.1 }
                ]
            }
        });

        // 人口比率
        if (popChart) popChart.destroy();
        popChart = new Chart(document.getElementById('popRatioChart').getContext('2d'), {
            type: 'line',
            data: {
                labels: years,
                datasets: [
                    { label: '0-14歳比率(%)', data: trend.map(t => (t.pop_0_14 && t.population) ? (t.pop_0_14 / t.population)*100 : null), borderColor: '#8b5cf6', tension: 0.1 }
                ]
            }
        });
    }
});
