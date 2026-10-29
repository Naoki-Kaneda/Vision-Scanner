// @ts-check
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Vision AI Scanner - スキャンの判断処理（画面に触れない関数）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// import/export を使わない通常のスクリプト。index.html で script.js より先に読み込み、
// ここで宣言した名前を script.js からそのまま使う（ビルド無しで CSP の script-src 'self' のまま動かすため）。
// 単体テストは tests/js/scan_core.test.js が node の vm で読み込んで行う。

/* exported ScanState, canTransition, compareImageHash, calcRetryDelay, computeResultFingerprint, isValidResult */

const MIN_RESULT_LENGTH = 5;         // 結果フィルター（テキスト系モードの最小文字数）
const RETRY_BASE_DELAY_MS = 5000;    // リトライ初回待機時間（指数バックオフ基底）
const RETRY_MAX_DELAY_MS = 60000;    // リトライ最大待機時間（60秒）

// ─── スキャン状態機械 ──────────────────────────────
const ScanState = Object.freeze({
    IDLE:              'IDLE',              // 待機中
    SCANNING:          'SCANNING',          // フレーム監視中
    ANALYZING:         'ANALYZING',         // API送信中
    PAUSED_ERROR:      'PAUSED_ERROR',      // エラー一時停止
    PAUSED_DUPLICATE:  'PAUSED_DUPLICATE',  // 重複検出で一時停止
    COOLDOWN:          'COOLDOWN',          // レート制限待機
});
/** @typedef {typeof ScanState[keyof typeof ScanState]} ScanStateValue スキャン状態の値 */

const SCAN_TRANSITIONS = Object.freeze({
    IDLE:              ['SCANNING'],
    SCANNING:          ['IDLE', 'ANALYZING', 'PAUSED_DUPLICATE'],
    ANALYZING:         ['IDLE', 'SCANNING', 'PAUSED_ERROR', 'PAUSED_DUPLICATE', 'COOLDOWN'],
    PAUSED_ERROR:      ['IDLE', 'SCANNING'],
    PAUSED_DUPLICATE:  ['IDLE', 'SCANNING'],
    COOLDOWN:          ['IDLE', 'SCANNING'],
});

/**
 * from から to への状態遷移が許されているかを返す。同じ状態への遷移は許す（何もしない扱い）。
 * @param {ScanStateValue} from - 現在の状態
 * @param {ScanStateValue} to - 遷移先の状態
 * @returns {boolean} 許されていれば true
 */
function canTransition(from, to) {
    if (from === to) return true;
    const allowed = SCAN_TRANSITIONS[from];
    return Boolean(allowed && allowed.includes(to));
}

/**
 * 2つの画像ハッシュの類似度を計算する（0.0〜1.0）。
 * @param {Uint8Array} hashA
 * @param {Uint8Array} hashB
 * @returns {number} 類似度（1.0=完全一致）
 */
function compareImageHash(hashA, hashB) {
    if (!hashA || !hashB || hashA.length !== hashB.length) return 0;
    let totalDiff = 0;
    for (let i = 0; i < hashA.length; i++) {
        totalDiff += Math.abs(hashA[i] - hashB[i]);
    }
    return 1 - totalDiff / (hashA.length * 255);
}

/**
 * 連続エラー回数から、再試行までの待ち時間（ミリ秒）を求める。
 * 指数バックオフ + ジッター: BASE × 2^(n-1) × [0.75, 1.25]、上限 RETRY_MAX_DELAY_MS。
 * 例（ジッターなし）: 5秒 → 10秒 → 20秒 → 40秒 → 60秒（上限）
 * @param {number} errorCount - 連続エラー回数（1以上）
 * @param {number} random - 0以上1未満の乱数（呼び出し側で Math.random() を渡す）
 * @returns {number} 待ち時間（ミリ秒）
 */
function calcRetryDelay(errorCount, random) {
    const jitter = 0.75 + random * 0.5;
    return Math.min(
        RETRY_BASE_DELAY_MS * Math.pow(2, errorCount - 1) * jitter,
        RETRY_MAX_DELAY_MS
    );
}

/**
 * API結果の「指紋」を生成する。同じ被写体なら同じ文字列を返す。
 * 結果が空やエラーの場合は null を返す（重複カウントしない）。
 * @param {Object} result - APIレスポンス
 * @param {string} mode - 検出モード（text/object/label/face/logo/classify/web）
 * @returns {string|null} 結果の指紋文字列
 */
function computeResultFingerprint(result, mode) {
    if (!result.ok) return null;

    // Web検索モード: best_guess をキーにする
    if (mode === 'web') {
        const detail = result.web_detail || {};
        return detail.best_guess || null;
    }

    // ラベル判定モード: OK/NG + 理由
    if (mode === 'label') {
        return `label:${result.label_detected}:${result.label_reason || ''}`;
    }

    // 共通: data 配列からラベルを抽出してソート結合
    if (!result.data || result.data.length === 0) return null;
    const labels = result.data
        .map(item => {
            let label = (item.label || '').trim();
            // 確信度部分を除去（"Apple - 95%" → "Apple"）
            label = label.replace(/\s*[-–]\s*\d+%\s*$/, '');
            return label.toLowerCase();
        })
        .filter(l => l.length > 0)
        .sort();
    if (labels.length === 0) return null;
    // 検出数プレフィックス + ラベル一覧で指紋を構成
    return `n${labels.length}:${labels.join('|')}`;
}

/**
 * ノイズや短すぎる結果を除外するフィルター。
 * @param {Object} item - 検出結果の1件（label を持つ）
 * @param {string} mode - 検出モード
 * @returns {boolean} 表示する結果なら true
 */
function isValidResult(item, mode) {
    const text = item.label || '';
    const cleaned = text.trim();
    // スコア付きラベルのモードは最小文字数フィルターをスキップ
    if (['object', 'face', 'logo'].includes(mode)) return cleaned.length > 0;
    if (cleaned.length < MIN_RESULT_LENGTH) return false;
    if (cleaned.startsWith('www.') || cleaned.startsWith('http')) return false;
    return true;
}
