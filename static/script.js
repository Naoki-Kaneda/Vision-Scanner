// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Vision AI Scanner - フロントエンドスクリプト
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// ─── 定数・設定 ──────────────────────────────────
const API_DAILY_LIMIT = 100;          // 1日のAPI呼び出し上限
const TARGET_BOX_RATIO = 0.6;        // ターゲットボックスの映像比率（60%）
const STABILITY_THRESHOLD = 30;      // 安定判定フレーム数（約1秒@30fps）
const MOTION_THRESHOLD = 15;         // フレーム間差分の閾値
const CAMERA_WIDTH = 1280;           // カメラ解像度（幅）
const CAMERA_HEIGHT = 720;           // カメラ解像度（高さ）
const JPEG_QUALITY = 0.95;           // キャプチャ画質
const MIN_RESULT_LENGTH = 5;         // 結果フィルター: 最小文字数

// ─── DOM要素の参照 ─────────────────────────────────
const video = document.getElementById('video-feed');
const canvas = document.getElementById('capture-canvas');
const ctx = canvas.getContext('2d');
const resultList = document.getElementById('result-list');
const btnScan = document.getElementById('btn-scan');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');

// ─── アプリケーション状態 ──────────────────────────
let isScanning = false;
let currentSource = 'camera';
let currentMode = 'text';
let isMirrored = false;
let isPausedByError = false;  // エラーによる一時停止状態
let retryTimerId = null;      // 再試行用タイマーID
let isAnalyzing = false;      // API呼び出し中フラグ（並行呼び出し防止）
let apiCallCount = 0;
let videoDevices = [];
let currentDeviceIndex = 0;
let lastFrameData = null;
let stabilityCounter = 0;

// 差分検出用キャンバス（毎フレーム生成せず再利用）
const motionCanvas = document.createElement('canvas');
motionCanvas.width = 64;
motionCanvas.height = 48;
const motionCtx = motionCanvas.getContext('2d');


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// API使用量管理
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** localStorage からAPI使用量を読み込む。日付が変わったらリセット。 */
function loadApiUsage() {
    const today = new Date().toDateString();
    const saved = localStorage.getItem('visionApiUsage');
    if (saved) {
        try {
            const data = JSON.parse(saved);
            apiCallCount = (data && data.date === today) ? (data.count || 0) : 0;
        } catch {
            // localStorageが壊れている場合はリセット
            apiCallCount = 0;
            localStorage.removeItem('visionApiUsage');
        }
    }
    updateApiCounter();
}

/** API使用量を localStorage に保存する。 */
function saveApiUsage() {
    localStorage.setItem('visionApiUsage', JSON.stringify({
        date: new Date().toDateString(),
        count: apiCallCount,
    }));
    updateApiCounter();
}

// ─── プロキシ設定制御 ──────────────────────────────
let currentProxyEnabled = false;

async function loadProxyConfig() {
    try {
        const res = await fetch('/api/config/proxy');
        if (res.ok) {
            const data = await res.json();
            updateProxyButton(data.enabled);
        }
    } catch (err) {
        console.error('プロキシ設定取得エラー:', err);
    }
}

async function toggleProxy() {
    const newState = !currentProxyEnabled;
    try {
        const res = await fetch('/api/config/proxy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: newState }),
        });
        if (res.ok) {
            const data = await res.json();
            updateProxyButton(data.status.enabled);
        } else {
            alert('プロキシ切り替えに失敗しました');
        }
    } catch (err) {
        console.error('プロキシ切り替えエラー:', err);
        alert('通信エラーが発生しました');
    }
}

function updateProxyButton(isEnabled) {
    currentProxyEnabled = isEnabled;
    const btn = document.getElementById('btn-proxy');
    if (!btn) return;

    if (isEnabled) {
        btn.innerText = 'Proxy: ON';
        btn.className = 'proxy-badge active';
        btn.title = 'クリックして無効化';
    } else {
        btn.innerText = 'Proxy: OFF';
        btn.className = 'proxy-badge inactive';
        btn.title = 'クリックして有効化';
    }
}

/** ヘッダーのAPIカウンター表示を更新する。 */
function updateApiCounter() {
    const counterEl = document.getElementById('api-counter');
    if (!counterEl) return;

    counterEl.textContent = `API: ${apiCallCount}/${API_DAILY_LIMIT}`;
    if (apiCallCount >= API_DAILY_LIMIT) {
        counterEl.style.color = '#ff3b3b';
    } else if (apiCallCount >= API_DAILY_LIMIT * 0.8) {
        counterEl.style.color = '#ffaa00';
    } else {
        // 日付リセット後に色を復帰
        counterEl.style.color = '';
    }

    // 上限到達時はStartボタンを無効化、それ以外は復帰
    if (apiCallCount >= API_DAILY_LIMIT) {
        btnScan.disabled = true;
        btnScan.innerHTML = '<span class="icon">⚠</span> API上限（本日分）';
        btnScan.style.opacity = '0.5';
        btnScan.style.cursor = 'not-allowed';
    } else {
        btnScan.disabled = false;
        btnScan.style.opacity = '';
        btnScan.style.cursor = '';
    }
}

/** API上限に達しているか判定する。達している場合はスキャンを停止。 */
function isApiLimitReached() {
    if (apiCallCount >= API_DAILY_LIMIT) {
        statusText.innerText = '⚠ API上限に達しました（本日分）';
        stopScanning();
        btnScan.disabled = true;
        btnScan.innerHTML = '<span class="icon">⚠</span> API上限（本日分）';
        btnScan.style.opacity = '0.5';
        btnScan.style.cursor = 'not-allowed';
        return true;
    }
    return false;
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// カメラ制御
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


/** カメラを初期化してHD映像を取得する。 */
async function setupCamera() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        videoDevices = devices.filter(d => d.kind === 'videoinput');

        // カメラが2台以上あれば切り替えボタンを表示
        if (videoDevices.length > 1) {
            document.getElementById('btn-switch-cam').style.display = 'inline-block';
        }

        const constraints = {
            video: {
                deviceId: videoDevices.length > 0
                    ? { exact: videoDevices[currentDeviceIndex].deviceId }
                    : undefined,
                width: { ideal: CAMERA_WIDTH },
                height: { ideal: CAMERA_HEIGHT },
            },
        };

        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        video.srcObject = stream;
        video.onloadedmetadata = () => video.play();
        currentSource = 'camera';
        updateSourceButtons();
    } catch (err) {
        console.error('カメラアクセスエラー:', err);
        alert('カメラへのアクセスが拒否されたか、カメラが見つかりません。');
    }
}

/** カメラデバイスを切り替える。 */
function toggleCameraDevice() {
    if (videoDevices.length < 2) return;
    if (video.srcObject) {
        video.srcObject.getTracks().forEach(track => track.stop());
    }
    currentDeviceIndex = (currentDeviceIndex + 1) % videoDevices.length;
    setupCamera();
}

/** 動画ファイルをアップロードして再生する。 */
function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    // カメラストリームを停止
    if (video.srcObject) {
        video.srcObject.getTracks().forEach(track => track.stop());
        video.srcObject = null;
    }

    // 前のBlob URLがあればリボークしてメモリリークを防止
    if (video.src && video.src.startsWith('blob:')) {
        URL.revokeObjectURL(video.src);
    }
    video.src = URL.createObjectURL(file);
    video.loop = true;
    video.play();
    currentSource = 'file';
    updateSourceButtons();
}

/** 入力ソースをカメラに切り替える。 */
function switchSource(source) {
    if (source === 'camera') {
        setupCamera();
    }
}

/** Camera / File ボタンのアクティブ状態を更新する。 */
function updateSourceButtons() {
    document.getElementById('btn-camera').classList.toggle('active', currentSource === 'camera');
    document.getElementById('btn-file').classList.toggle('active', currentSource === 'file');
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// スキャン・安定化検出
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** スキャンの開始/停止を切り替える。 */
function toggleScanning() {
    isScanning ? stopScanning() : startScanning();
}

/** スキャンを開始し、安定化検出ループを起動する。 */
function startScanning() {
    isScanning = true;
    btnScan.innerHTML = '<span class="icon">■</span> Stop';
    btnScan.classList.add('scanning');
    document.querySelector('.video-container').classList.add('scanning');
    statusDot.classList.add('active');
    statusText.innerText = '静止を待っています...';

    // 安定化バーを表示
    document.getElementById('stability-bar-container').style.display = 'block';
    document.getElementById('stability-bar-fill').style.width = '0%';

    requestAnimationFrame(scanLoop);
}

/** スキャンを停止してUIをリセットする。 */
function stopScanning() {
    isScanning = false;
    isPausedByError = false;
    if (retryTimerId) {
        clearTimeout(retryTimerId);
        retryTimerId = null;
    }
    btnScan.innerHTML = '<span class="icon">▶</span> Start';
    btnScan.classList.remove('scanning');
    document.querySelector('.video-container').classList.remove('scanning');
    statusDot.classList.remove('active');
    statusText.innerText = '準備完了';

    // 安定化バーを非表示
    document.getElementById('stability-bar-container').style.display = 'none';
}

/** requestAnimationFrameベースのスキャンループ。 */
function scanLoop() {
    if (!isScanning) return;
    checkStabilityAndCapture();
    requestAnimationFrame(scanLoop);
}

/** フレーム間差分で安定状態を検出し、安定したらキャプチャする。 */
function checkStabilityAndCapture() {
    if (!video.videoWidth) return;

    // 再利用キャンバスでフレーム差分を計算
    motionCtx.drawImage(video, 0, 0, motionCanvas.width, motionCanvas.height);

    const currentFrameData = motionCtx.getImageData(0, 0, motionCanvas.width, motionCanvas.height).data;
    const barFill = document.getElementById('stability-bar-fill');

    if (lastFrameData) {
        let diff = 0;
        for (let i = 0; i < currentFrameData.length; i += 4) {
            diff += Math.abs(currentFrameData[i] - lastFrameData[i]);
            diff += Math.abs(currentFrameData[i + 1] - lastFrameData[i + 1]);
            diff += Math.abs(currentFrameData[i + 2] - lastFrameData[i + 2]);
        }
        const avgDiff = diff / (motionCanvas.width * motionCanvas.height);

        if (avgDiff < MOTION_THRESHOLD) {
            // 安定状態
            stabilityCounter++;
            const progress = Math.min((stabilityCounter / STABILITY_THRESHOLD) * 100, 100);
            barFill.style.width = progress + '%';
            barFill.classList.remove('captured');
            statusText.innerText = `安定化中... ${Math.round(progress)}%`;

            if (stabilityCounter >= STABILITY_THRESHOLD) {
                // 安定完了 → キャプチャ実行
                barFill.style.width = '100%';
                barFill.classList.add('captured');
                statusText.innerText = '📸 撮影完了！';
                captureAndAnalyze();
                stabilityCounter = 0;

                // 短い遅延後にバーをリセット
                setTimeout(() => {
                    if (isScanning) {
                        barFill.style.width = '0%';
                        barFill.classList.remove('captured');
                        statusText.innerText = '静止を待っています...';
                    }
                }, 1500);
            }
        } else {
            // 動きを検出 → カウンターリセット
            stabilityCounter = 0;
            barFill.style.width = '0%';
            barFill.classList.remove('captured');
            statusText.innerText = '動きを検出中...';
        }
    }

    lastFrameData = currentFrameData;
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 画像キャプチャ・API解析
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** ターゲットボックス内の映像をキャプチャしてAPIに送信する。 */
async function captureAndAnalyze() {
    if (!video.videoWidth) return;
    if (isAnalyzing) return;  // 前回のAPI呼び出し中は新しいキャプチャをスキップ
    if (isApiLimitReached()) return;

    isAnalyzing = true;

    // ターゲットボックス内のみをクロップして送信
    const srcX = video.videoWidth * (1 - TARGET_BOX_RATIO) / 2;
    const srcY = video.videoHeight * (1 - TARGET_BOX_RATIO) / 2;
    const srcW = video.videoWidth * TARGET_BOX_RATIO;
    const srcH = video.videoHeight * TARGET_BOX_RATIO;

    canvas.width = srcW;
    canvas.height = srcH;
    ctx.drawImage(video, srcX, srcY, srcW, srcH, 0, 0, srcW, srcH);

    const imageData = canvas.toDataURL('image/jpeg', JPEG_QUALITY);

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: imageData, mode: currentMode }),
        });

        const result = await response.json();

        // サーバー側レート制限: 再試行スケジュールで連射を防止
        if (response.status === 429) {
            statusText.innerText = `⚠ ${result.message || 'リクエスト制限中'}`;
            scheduleRetry();
            return;
        }

        // 成功時のみカウント加算（失敗時はAPI消費しない）
        if (result.ok) {
            apiCallCount++;
            saveApiUsage();
        }

        // 統一レスポンス形式に対応
        if (result.ok && result.data && result.data.length > 0) {
            result.data
                .filter(isValidResult)
                .forEach(addResultItem);
        } else if (!result.ok) {
            // UIにエラーを表示し、一定時間スキャンを一時停止
            const errorMsg = result.message || `サーバーエラー (${result.error_code})`;
            statusText.innerText = `⚠ ${errorMsg}`;
            console.error(`APIエラー [${result.error_code}]:`, result.message);
            scheduleRetry();
        }
    } catch (err) {
        // 通信失敗もUIに表示
        statusText.innerText = '⚠ 通信エラー。再試行します...';
        console.error('通信エラー:', err);
        scheduleRetry();
    } finally {
        isAnalyzing = false;
    }
}

/**
 * エラー発生時の再試行スケジュール
 */
function scheduleRetry() {
    if (!isScanning && !isPausedByError) return; // 手動停止済みななら何もしない

    isScanning = false;
    isPausedByError = true;

    if (retryTimerId) clearTimeout(retryTimerId);

    retryTimerId = setTimeout(() => {
        retryTimerId = null;
        // まだエラー停止状態かつ手動停止されていなければ再開
        if (isPausedByError) {
            isScanning = true;
            isPausedByError = false;
            statusText.innerText = '静止を待っています...';
            requestAnimationFrame(scanLoop);
        }
    }, 5000);
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 結果表示・フィルター
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** ノイズや短すぎる結果を除外するフィルター。 */
function isValidResult(text) {
    const cleaned = text.trim();
    if (cleaned.length < MIN_RESULT_LENGTH) return false;
    if (cleaned.startsWith('www.') || cleaned.startsWith('http')) return false;
    return true;
}

/** 検出結果をタイムスタンプ付きで結果リストに追加する。 */
function addResultItem(text) {
    const cleanText = text.trim();
    if (!cleanText) return;

    const timeStr = new Date().toLocaleTimeString();

    // プレースホルダーを除去
    const placeholder = document.querySelector('.placeholder-text');
    if (placeholder) placeholder.remove();

    const div = document.createElement('div');
    div.className = 'result-item';

    // XSS対策: innerHTML ではなく DOM操作でテキストを挿入する
    const timeSpan = document.createElement('span');
    timeSpan.className = 'timestamp';
    timeSpan.textContent = `[${timeStr}]`;

    const textNode = document.createTextNode(` ${cleanText}`);

    div.appendChild(timeSpan);
    div.appendChild(textNode);
    resultList.prepend(div);
}

/** 結果リストをクリアする。 */
function clearResults() {
    // XSS対策ポリシーの統一: innerHTML ではなく DOM API を使用
    while (resultList.firstChild) {
        resultList.removeChild(resultList.firstChild);
    }
    const placeholder = document.createElement('div');
    placeholder.className = 'placeholder-text';
    placeholder.textContent = 'スキャンして検出を開始...';
    resultList.appendChild(placeholder);
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// UI制御（ミラー・モード切替）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** ミラー（左右反転）の状態をDOMに反映する。 */
function updateMirrorState() {
    const container = document.querySelector('.video-container');
    container.classList.toggle('mirrored', isMirrored);
}

/** ミラー（左右反転）を切り替える。 */
function toggleMirror() {
    isMirrored = !isMirrored;
    updateMirrorState();
}

/** テキスト / 物体検出モードを切り替える。 */
function setMode(mode) {
    currentMode = mode;
    document.getElementById('mode-text').classList.toggle('active', mode === 'text');
    document.getElementById('mode-object').classList.toggle('active', mode === 'object');
    clearResults();
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 初期化
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** アプリケーションを初期化する。 */
function init() {
    setupCamera();
    updateMirrorState();
    loadApiUsage();
    loadProxyConfig();
}

document.addEventListener('DOMContentLoaded', init);
