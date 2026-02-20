// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Vision AI Scanner - フロントエンドスクリプト
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// ─── 定数・設定 ──────────────────────────────────
const API_DAILY_LIMIT = 100;          // 1日のAPI呼び出し上限
const API_WARNING_RATIO = 0.8;       // API上限の警告表示閾値（80%で黄色）
const TARGET_BOX_RATIO = 0.6;        // ターゲットボックスの映像比率（60%）
const STABILITY_THRESHOLD = 30;      // 安定判定フレーム数（約1秒@30fps）
const MOTION_THRESHOLD = 30;         // フレーム間差分の閾値（カメラノイズ耐性を確保）
const MOTION_CANVAS_WIDTH = 64;      // モーション検出用キャンバス幅
const MOTION_CANVAS_HEIGHT = 48;     // モーション検出用キャンバス高さ
const CAMERA_WIDTH = 1280;           // カメラ解像度（幅）
const CAMERA_HEIGHT = 720;           // カメラ解像度（高さ）
const JPEG_QUALITY = 0.95;           // キャプチャ画質
const MIN_RESULT_LENGTH = 5;         // 結果フィルター: 最小文字数
const LABEL_MAX_LENGTH = 25;         // バウンディングボックスのラベル最大文字数
const RETRY_DELAY_MS = 5000;         // エラー後の再試行待機時間（ミリ秒）
const CAPTURE_RESET_DELAY_MS = 1500; // 撮影完了後のバーリセット遅延（ミリ秒）
// true にするとクライアント側でも日次上限を強制。既定は false（サーバー側429に委譲）
const ENFORCE_CLIENT_DAILY_LIMIT = false;

// ─── DOM要素の参照（init() で DOMContentLoaded 後に取得） ────
let video, canvas, ctx, overlayCanvas, overlayCtx;
let resultList, btnScan, statusDot, statusText;
let videoContainer, stabilityBarContainer, stabilityBarFill;
let btnProxy, apiCounter, btnSwitchCam;
let btnCamera, btnFile, modeText, modeObject;

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
motionCanvas.width = MOTION_CANVAS_WIDTH;
motionCanvas.height = MOTION_CANVAS_HEIGHT;
const motionCtx = motionCanvas.getContext('2d', { willReadFrequently: true });


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

/** プロキシ状態の表示を更新する（表示のみ、切替はCLI操作）。 */
function updateProxyButton(isEnabled) {
    currentProxyEnabled = isEnabled;
    if (!btnProxy) return;

    if (isEnabled) {
        btnProxy.textContent = 'Proxy: ON';
        btnProxy.className = 'proxy-badge active';
    } else {
        btnProxy.textContent = 'Proxy: OFF';
        btnProxy.className = 'proxy-badge inactive';
    }
}

/** スキャンボタンを無効化する（API上限到達時）。 */
function disableScanButton(message) {
    if (!btnScan) return;
    btnScan.disabled = true;
    btnScan.innerHTML = `<span class="icon">⚠</span> ${message}`;
    btnScan.style.opacity = '0.5';
    btnScan.style.cursor = 'not-allowed';
}

/** ヘッダーのAPIカウンター表示を更新する。 */
function updateApiCounter() {
    if (!apiCounter) return;

    apiCounter.textContent = `API: ${apiCallCount}/${API_DAILY_LIMIT}`;
    if (apiCallCount >= API_DAILY_LIMIT) {
        apiCounter.style.color = '#ff3b3b';
    } else if (apiCallCount >= API_DAILY_LIMIT * API_WARNING_RATIO) {
        apiCounter.style.color = '#ffaa00';
    } else {
        // 日付リセット後に色を復帰
        apiCounter.style.color = '';
    }

    // 既定ではボタンロックを行わない（サーバー側のレート制限を信頼）
    if (ENFORCE_CLIENT_DAILY_LIMIT && apiCallCount >= API_DAILY_LIMIT) {
        disableScanButton('API上限（本日分）');
    } else if (btnScan) {
        btnScan.disabled = false;
        btnScan.style.opacity = '';
        btnScan.style.cursor = '';
    }
}

/** API上限に達しているか判定する。達している場合はスキャンを停止。 */
function isApiLimitReached() {
    if (ENFORCE_CLIENT_DAILY_LIMIT && apiCallCount >= API_DAILY_LIMIT) {
        statusText.textContent = '⚠ API上限に達しました（本日分）';
        stopScanning();
        disableScanButton('API上限（本日分）');
        return true;
    }
    return false;
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// カメラ制御
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


/** カメラストリームを停止する。 */
function stopCameraStream() {
    if (video.srcObject) {
        video.srcObject.getTracks().forEach(track => track.stop());
        video.srcObject = null;
    }
}

/** カメラを初期化してHD映像を取得する。 */
async function setupCamera() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        videoDevices = devices.filter(d => d.kind === 'videoinput');

        // カメラが2台以上あれば切り替えボタンを表示
        if (videoDevices.length > 1) {
            btnSwitchCam.classList.remove('hidden');
        }

        // deviceId が空文字の場合（権限未付与）は exact を使わない
        const targetId = videoDevices[currentDeviceIndex]?.deviceId;
        const constraints = {
            video: {
                deviceId: targetId ? { exact: targetId } : undefined,
                width: { ideal: CAMERA_WIDTH },
                height: { ideal: CAMERA_HEIGHT },
            },
        };

        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia(constraints);
        } catch (constraintErr) {
            // exact deviceId で失敗した場合、deviceId なしでリトライ
            console.warn('指定デバイスでの取得に失敗、フォールバック:', constraintErr.name);
            stream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: CAMERA_WIDTH }, height: { ideal: CAMERA_HEIGHT } },
            });
        }

        video.srcObject = stream;
        await video.play().catch(() => {});
        currentSource = 'camera';
        updateSourceButtons();

        // 権限付与後にデバイスリストを更新（deviceId が取得可能になる）
        const updated = await navigator.mediaDevices.enumerateDevices();
        videoDevices = updated.filter(d => d.kind === 'videoinput');
        if (videoDevices.length > 1) {
            btnSwitchCam.classList.remove('hidden');
        }
    } catch (err) {
        console.error('カメラアクセスエラー:', err);
        alert('カメラへのアクセスが拒否されたか、カメラが見つかりません。');
    }
}

/** カメラデバイスを切り替える。 */
function toggleCameraDevice() {
    if (videoDevices.length < 2) return;
    stopCameraStream();
    currentDeviceIndex = (currentDeviceIndex + 1) % videoDevices.length;
    setupCamera();
}

/** 動画ファイルをアップロードして再生する。 */
function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    stopCameraStream();

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
    if (btnCamera) btnCamera.classList.toggle('active', currentSource === 'camera');
    if (btnFile) btnFile.classList.toggle('active', currentSource === 'file');
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// スキャン・安定化検出
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** スキャンの開始/停止を切り替える（チャタリング防止: タイムスタンプガード）。 */
let lastToggleTime = 0;
function toggleScanning() {
    const now = Date.now();
    if (now - lastToggleTime < 800) return;
    lastToggleTime = now;
    // isScanning または isPausedByError（エラー再試行待ち）なら停止
    (isScanning || isPausedByError) ? stopScanning() : startScanning();
}

/** スキャンを開始し、安定化検出ループを起動する。 */
function startScanning() {
    // エラー再試行タイマーが残っていればクリア（2重ループ防止）
    isPausedByError = false;
    if (retryTimerId) {
        clearTimeout(retryTimerId);
        retryTimerId = null;
    }

    isScanning = true;
    btnScan.innerHTML = '<span class="icon">■</span> ストップ';
    btnScan.classList.add('scanning');
    if (videoContainer) videoContainer.classList.add('scanning');
    if (statusDot) statusDot.classList.add('active');
    if (statusText) statusText.textContent = 'スキャン中';

    // 安定化バーを表示
    if (stabilityBarContainer) stabilityBarContainer.classList.remove('hidden');
    if (stabilityBarFill) stabilityBarFill.style.width = '0%';

    scanFrameCount = 0;
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
    clearOverlay();
    btnScan.innerHTML = '<span class="icon">▶</span> スタート';
    btnScan.classList.remove('scanning');
    if (videoContainer) videoContainer.classList.remove('scanning');
    if (statusDot) statusDot.classList.remove('active');
    if (statusText) statusText.textContent = '準備完了';

    // 安定化バーを非表示
    if (stabilityBarContainer) stabilityBarContainer.classList.add('hidden');
}

/** requestAnimationFrameベースのスキャンループ。 */
let scanFrameCount = 0;
function scanLoop() {
    if (!isScanning) return;
    scanFrameCount++;
    checkStabilityAndCapture();
    requestAnimationFrame(scanLoop);
}

/**
 * フレーム間差分で安定状態を検出し、安定したらキャプチャする。
 * statusText は状態遷移時のみ更新（チラつき防止）。進捗はプログレスバーのみ。
 */
let lastStabilityState = 'idle'; // idle | stabilizing | captured | moving
function checkStabilityAndCapture() {
    if (!video.videoWidth) return;

    // 再利用キャンバスでフレーム差分を計算
    motionCtx.drawImage(video, 0, 0, motionCanvas.width, motionCanvas.height);

    const currentFrameData = motionCtx.getImageData(0, 0, motionCanvas.width, motionCanvas.height).data;

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
            if (stabilityBarFill) {
                stabilityBarFill.style.width = progress + '%';
                stabilityBarFill.classList.remove('captured');
            }
            // テキストは変更しない（プログレスバーのみで進捗を表示）
            lastStabilityState = 'stabilizing';

            if (stabilityCounter >= STABILITY_THRESHOLD) {
                // 安定完了 → キャプチャ実行
                lastStabilityState = 'captured';
                if (stabilityBarFill) {
                    stabilityBarFill.style.width = '100%';
                    stabilityBarFill.classList.add('captured');
                }
                if (statusText) statusText.textContent = '解析中...';
                captureAndAnalyze();
                stabilityCounter = 0;

                // 短い遅延後にバーをリセット
                setTimeout(() => {
                    if (isScanning) {
                        lastStabilityState = 'idle';
                        if (stabilityBarFill) {
                            stabilityBarFill.style.width = '0%';
                            stabilityBarFill.classList.remove('captured');
                        }
                        if (statusText) statusText.textContent = 'スキャン中';
                    }
                }, CAPTURE_RESET_DELAY_MS);
            }
        } else {
            // 動きを検出 → カウンターリセット
            stabilityCounter = 0;
            if (stabilityBarFill) {
                stabilityBarFill.style.width = '0%';
                stabilityBarFill.classList.remove('captured');
            }
            // テキストは変更しない（バーが0%に戻ることで動き検出を表現）
            lastStabilityState = 'moving';
        }
    }

    lastFrameData = currentFrameData;
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// バウンディングボックス描画
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** オーバーレイCanvasをクリアする。 */
function clearOverlay() {
    if (!overlayCanvas) return;
    overlayCanvas.width = overlayCanvas.width;
}

/**
 * 検出結果のバウンディングボックスをオーバーレイCanvasに描画する。
 * テキストモード: 緑色の枠線（ラベル非表示）
 * 物体モード: 赤色の枠線＋ラベル表示
 *
 * @param {Array} data - [{label, bounds}, ...] 検出結果
 * @param {Array|null} imageSize - [width, height] テキストモードのピクセル基準サイズ
 */
function drawBoundingBoxes(data, imageSize) {
    clearOverlay();
    if (!videoContainer || !overlayCtx) return;

    const rect = videoContainer.getBoundingClientRect();
    overlayCanvas.width = rect.width;
    overlayCanvas.height = rect.height;

    // ターゲットボックスの表示領域（コンテナ基準）
    const offsetRatio = (1 - TARGET_BOX_RATIO) / 2;
    const targetX = rect.width * offsetRatio;
    const targetY = rect.height * offsetRatio;
    const targetW = rect.width * TARGET_BOX_RATIO;
    const targetH = rect.height * TARGET_BOX_RATIO;

    const isTextMode = currentMode === 'text';
    const boxColor = isTextMode ? '#00ff88' : '#ff3b3b';
    const bgColor = isTextMode ? 'rgba(0, 255, 136, 0.7)' : 'rgba(255, 59, 59, 0.7)';

    overlayCtx.lineWidth = 2;
    overlayCtx.font = '11px "Inter", "Noto Sans JP", sans-serif';

    data.forEach(item => {
        if (!item.bounds || item.bounds.length < 4) return;

        // 正規化座標（0〜1）に変換
        let normBounds;
        if (isTextMode && imageSize && imageSize[0] > 0 && imageSize[1] > 0) {
            // テキストモード: ピクセル座標 → 正規化座標
            normBounds = item.bounds.map(([x, y]) => [
                x / imageSize[0],
                y / imageSize[1],
            ]);
        } else {
            // 物体モード: 既に正規化座標（0〜1）
            normBounds = item.bounds;
        }

        // ミラー反転時はX座標を反転
        if (isMirrored) {
            normBounds = normBounds.map(([nx, ny]) => [1 - nx, ny]);
        }

        // ターゲットボックス内のCanvas座標に変換
        const pts = normBounds.map(([nx, ny]) => [
            targetX + nx * targetW,
            targetY + ny * targetH,
        ]);

        // 矩形を描画
        overlayCtx.strokeStyle = boxColor;
        overlayCtx.beginPath();
        overlayCtx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) {
            overlayCtx.lineTo(pts[i][0], pts[i][1]);
        }
        overlayCtx.closePath();
        overlayCtx.stroke();

        // 物体モードのみラベルを表示（テキストモードは枠だけで十分）
        if (!isTextMode) {
            const labelText = item.label.length > LABEL_MAX_LENGTH
                ? item.label.substring(0, LABEL_MAX_LENGTH) + '…'
                : item.label;
            const metrics = overlayCtx.measureText(labelText);
            const labelX = pts[0][0];
            const labelY = pts[0][1] - 4;

            // ラベル背景
            overlayCtx.fillStyle = bgColor;
            overlayCtx.fillRect(labelX, labelY - 13, metrics.width + 6, 16);

            // ラベルテキスト
            overlayCtx.fillStyle = '#fff';
            overlayCtx.fillText(labelText, labelX + 3, labelY);
        }
    });
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 画像キャプチャ・API解析
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** ターゲットボックス内の映像をキャプチャしてAPIに送信する。 */
async function captureAndAnalyze() {
    if (!video.videoWidth || isAnalyzing || isApiLimitReached()) return;
    isAnalyzing = true;
    clearOverlay();

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

        // JSONパース失敗に備えた安全なパース（413等でHTML応答の場合）
        let result;
        try {
            result = await response.json();
        } catch {
            statusText.textContent = `⚠ サーバーエラー (${response.status})`;
            scheduleRetry();
            return;
        }

        // サーバー側レート制限: 再試行スケジュールで連射を防止
        if (response.status === 429) {
            statusText.textContent = `⚠ ${result.message || 'リクエスト制限中'}`;
            scheduleRetry();
            return;
        }

        // 成功時のみカウント加算（失敗時はAPI消費しない）
        if (result.ok) {
            apiCallCount++;
            saveApiUsage();
        }

        // 統一レスポンス形式に対応（data は {label, bounds} オブジェクト配列）
        if (result.ok && result.data && result.data.length > 0) {
            drawBoundingBoxes(result.data, result.image_size);
            result.data
                .filter(isValidResult)
                .forEach(addResultItem);
        } else if (!result.ok) {
            // UIにエラーを表示し、一定時間スキャンを一時停止
            const errorMsg = result.message || `サーバーエラー (${result.error_code})`;
            statusText.textContent = `⚠ ${errorMsg}`;
            console.error(`APIエラー [${result.error_code}]:`, result.message);
            scheduleRetry();
        }
    } catch (err) {
        // 通信失敗もUIに表示
        statusText.textContent = '⚠ 通信エラー。再試行します...';
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
            if (statusText) statusText.textContent = 'スキャン中';
            requestAnimationFrame(scanLoop);
        }
    }, RETRY_DELAY_MS);
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 結果表示・フィルター
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** ノイズや短すぎる結果を除外するフィルター。 */
function isValidResult(item) {
    const text = item.label || '';
    const cleaned = text.trim();
    // 物体モードは信頼度スコア付きラベルなので最小文字数フィルターをスキップ
    if (currentMode === 'object') return cleaned.length > 0;
    if (cleaned.length < MIN_RESULT_LENGTH) return false;
    if (cleaned.startsWith('www.') || cleaned.startsWith('http')) return false;
    return true;
}

/** 検出結果をタイムスタンプ付きで結果リストに追加する。 */
function addResultItem(item) {
    const cleanText = (item.label || '').trim();
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
    if (videoContainer) videoContainer.classList.toggle('mirrored', isMirrored);
}

/** ミラー（左右反転）を切り替える。 */
function toggleMirror() {
    isMirrored = !isMirrored;
    updateMirrorState();
}

/** テキスト / 物体検出モードを切り替える。 */
function setMode(mode) {
    currentMode = mode;
    if (modeText) modeText.classList.toggle('active', mode === 'text');
    if (modeObject) modeObject.classList.toggle('active', mode === 'object');
    clearResults();
    clearOverlay();
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 初期化
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** アプリケーションを初期化する。 */
function init() {
    // ─── DOM要素の取得（DOMContentLoaded 保証下で安全に取得） ──
    videoContainer = document.querySelector('.video-container');
    video = document.getElementById('video-feed');
    canvas = document.getElementById('capture-canvas');
    overlayCanvas = document.getElementById('overlay-canvas');
    resultList = document.getElementById('result-list');
    btnScan = document.getElementById('btn-scan');
    statusDot = document.getElementById('status-dot');
    statusText = document.getElementById('status-text');
    stabilityBarContainer = document.getElementById('stability-bar-container');
    stabilityBarFill = document.getElementById('stability-bar-fill');
    btnProxy = document.getElementById('btn-proxy');
    apiCounter = document.getElementById('api-counter');
    btnSwitchCam = document.getElementById('btn-switch-cam');
    btnCamera = document.getElementById('btn-camera');
    btnFile = document.getElementById('btn-file');
    modeText = document.getElementById('mode-text');
    modeObject = document.getElementById('mode-object');
    const fileInput = document.getElementById('file-input');
    // 旧テンプレート互換: idが無い場合は既存クラスから取得
    const btnMirror = document.getElementById('btn-mirror')
        || document.querySelector('.video-tools .tool-btn');
    const btnClear = document.getElementById('btn-clear')
        || document.querySelector('.clear-btn');

    // 古いテンプレート/キャッシュ混在時のクラッシュ防止
    if (!canvas && videoContainer) {
        canvas = document.createElement('canvas');
        canvas.id = 'capture-canvas';
        canvas.className = 'hidden';
        videoContainer.appendChild(canvas);
    }
    if (!overlayCanvas && videoContainer) {
        overlayCanvas = document.createElement('canvas');
        overlayCanvas.id = 'overlay-canvas';
        videoContainer.appendChild(overlayCanvas);
    }

    ctx = canvas ? canvas.getContext('2d') : null;
    overlayCtx = overlayCanvas ? overlayCanvas.getContext('2d') : null;

    // ─── 必須要素チェック（video / btnScan のみ致命的） ──
    if (!video || !btnScan) {
        console.error('[init] 致命的: video または btnScan が見つかりません。');
        return;
    }

    // ─── イベントリスナー登録（全要素にnullガード付き） ──
    if (btnCamera) btnCamera.addEventListener('click', () => switchSource('camera'));
    if (btnSwitchCam) btnSwitchCam.addEventListener('click', toggleCameraDevice);
    if (btnFile && fileInput) btnFile.addEventListener('click', () => fileInput.click());
    if (fileInput) fileInput.addEventListener('change', handleFileUpload);
    if (btnMirror) btnMirror.addEventListener('click', toggleMirror);
    if (modeText) modeText.addEventListener('click', () => setMode('text'));
    if (modeObject) modeObject.addEventListener('click', () => setMode('object'));
    btnScan.addEventListener('click', toggleScanning);
    if (btnClear) btnClear.addEventListener('click', clearResults);

    setupCamera();
    updateMirrorState();
    loadApiUsage();
    loadProxyConfig();
}

document.addEventListener('DOMContentLoaded', init);
