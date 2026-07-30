import L from 'leaflet';

let map = null;

// マップの初期化
function initMap() {
    // 関東・東北エリアが見渡せるように初期表示 (東京と仙台の中間あたり)
    map = L.map('map').setView([37.5, 140.0], 7);

    // 基本レイヤー (OpenStreetMap)
    const baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    // ハザードマップレイヤー (国土地理院)
    const floodLayer = L.tileLayer('https://disaportaldata.gsi.go.jp/raster/01_flood_l2_shinsuishin_data/{z}/{x}/{y}.png', {
        attribution: '国土地理院 重ねるハザードマップ',
        opacity: 0.7
    });
    
    const landslideLayer = L.tileLayer('https://disaportaldata.gsi.go.jp/raster/05_dosekiryukeikaikuiki/{z}/{x}/{y}.png', {
        attribution: '国土地理院 重ねるハザードマップ',
        opacity: 0.7
    });
    
    const tsunamiLayer = L.tileLayer('https://disaportaldata.gsi.go.jp/raster/04_tsunami_newlegend_data/{z}/{x}/{y}.png', {
        attribution: '国土地理院 重ねるハザードマップ',
        opacity: 0.7
    });

    const landformLayer = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/experimental_landform/{z}/{x}/{y}.png', {
        attribution: '国土地理院 地形分類（自然地形）',
        opacity: 0.7
    });

    const activeFaultLayer = L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/afm/{z}/{x}/{y}.png', {
        attribution: '国土地理院 都市圏活断層図',
        opacity: 0.7
    });

    // レイヤーコントロールの追加
    const overlayMaps = {
        "洪水浸水想定区域": floodLayer,
        "土砂災害警戒区域": landslideLayer,
        "津波浸水想定": tsunamiLayer,
        "地形分類 (地盤リスク)": landformLayer,
        "都市圏活断層図": activeFaultLayer
    };
    
    L.control.layers(null, overlayMaps, { collapsed: false }).addTo(map);
}

// アプリ起動
document.addEventListener('DOMContentLoaded', () => {
    initMap();
});
