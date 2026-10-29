// static/scan_core.js の単体テスト（npm test = node --test）
'use strict';

const { describe, test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/**
 * scan_core.js をブラウザと同じ「通常のスクリプト」として読み込み、宣言された名前を取り出す。
 * 本番のファイルに module.exports を足さずに済むよう、末尾に置いた式の値で受け取る。
 * （vm の別環境で作られた配列・オブジェクトは deepStrictEqual で比べられないので、値は文字列や数値で確かめる）
 */
function loadScanCore() {
    const code = fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'scan_core.js'), 'utf8');
    return vm.runInNewContext(`${code}
;({ ScanState, SCAN_TRANSITIONS, canTransition, compareImageHash, calcRetryDelay,
    computeResultFingerprint, isValidResult, RETRY_BASE_DELAY_MS, RETRY_MAX_DELAY_MS })`);
}

const core = loadScanCore();
const { ScanState } = core;

describe('canTransition（状態遷移の可否）', () => {
    test('待機中からはスキャン開始だけ許す', () => {
        assert.equal(core.canTransition(ScanState.IDLE, ScanState.SCANNING), true);
        assert.equal(core.canTransition(ScanState.IDLE, ScanState.ANALYZING), false);
        assert.equal(core.canTransition(ScanState.IDLE, ScanState.COOLDOWN), false);
    });

    test('解析中からはすべての後続状態へ移れる', () => {
        for (const to of ['IDLE', 'SCANNING', 'PAUSED_ERROR', 'PAUSED_DUPLICATE', 'COOLDOWN']) {
            assert.equal(core.canTransition(ScanState.ANALYZING, to), true, to);
        }
    });

    test('一時停止・クールダウンから解析へ直接は移れない', () => {
        for (const from of ['PAUSED_ERROR', 'PAUSED_DUPLICATE', 'COOLDOWN']) {
            assert.equal(core.canTransition(from, ScanState.ANALYZING), false, from);
        }
    });

    test('同じ状態への遷移は許す', () => {
        for (const state of Object.values(ScanState)) {
            assert.equal(core.canTransition(state, state), true, state);
        }
    });

    test('遷移表はすべての状態を持ち、遷移先もすべて定義済みの状態', () => {
        const states = Object.values(ScanState);
        assert.equal(Object.keys(core.SCAN_TRANSITIONS).sort().join(','), [...states].sort().join(','));
        for (const targets of Object.values(core.SCAN_TRANSITIONS)) {
            for (const to of targets) assert.ok(states.includes(to), to);
        }
    });
});

describe('compareImageHash（画像ハッシュの類似度）', () => {
    test('同じハッシュは 1', () => {
        const hash = new Uint8Array([0, 128, 255, 64]);
        assert.equal(core.compareImageHash(hash, hash), 1);
    });

    test('真っ黒と真っ白は 0', () => {
        assert.equal(core.compareImageHash(new Uint8Array(64).fill(0), new Uint8Array(64).fill(255)), 0);
    });

    test('半分だけ違えば 0.5', () => {
        const a = new Uint8Array([0, 0]);
        const b = new Uint8Array([0, 255]);
        assert.equal(core.compareImageHash(a, b), 0.5);
    });

    test('長さが違う・片方が無いときは 0（同一とみなさない）', () => {
        assert.equal(core.compareImageHash(new Uint8Array(4), new Uint8Array(8)), 0);
        assert.equal(core.compareImageHash(null, new Uint8Array(4)), 0);
    });
});

describe('calcRetryDelay（再試行までの待ち時間）', () => {
    // random=0.5 のときジッターは 1.0 倍
    test('ジッターなしなら 5秒 → 10秒 → 20秒 → 40秒 → 60秒（上限）', () => {
        const delays = [1, 2, 3, 4, 5].map(n => core.calcRetryDelay(n, 0.5));
        assert.equal(delays.join(','), '5000,10000,20000,40000,60000');
    });

    test('ジッターは 0.75〜1.25 倍', () => {
        assert.equal(core.calcRetryDelay(1, 0), core.RETRY_BASE_DELAY_MS * 0.75);
        assert.ok(core.calcRetryDelay(1, 0.999) < core.RETRY_BASE_DELAY_MS * 1.25);
    });

    test('何回失敗しても上限を超えない', () => {
        assert.equal(core.calcRetryDelay(30, 0.999), core.RETRY_MAX_DELAY_MS);
    });
});

describe('computeResultFingerprint（結果の指紋）', () => {
    test('失敗した結果は null（重複として数えない）', () => {
        assert.equal(core.computeResultFingerprint({ ok: false, data: [{ label: 'apple' }] }, 'object'), null);
    });

    test('ラベルは確信度を除き、小文字にして並べ替える', () => {
        const result = { ok: true, data: [{ label: 'Banana - 90%' }, { label: ' Apple ' }] };
        assert.equal(core.computeResultFingerprint(result, 'object'), 'n2:apple|banana');
    });

    test('並び順が違っても同じ被写体なら同じ指紋', () => {
        const a = { ok: true, data: [{ label: 'Cat - 80%' }, { label: 'Dog - 70%' }] };
        const b = { ok: true, data: [{ label: 'Dog - 75%' }, { label: 'Cat - 85%' }] };
        assert.equal(core.computeResultFingerprint(a, 'object'), core.computeResultFingerprint(b, 'object'));
    });

    test('結果が空・ラベルが空なら null', () => {
        assert.equal(core.computeResultFingerprint({ ok: true, data: [] }, 'text'), null);
        assert.equal(core.computeResultFingerprint({ ok: true, data: [{ label: '  ' }] }, 'text'), null);
    });

    test('Web モードは best_guess を使う', () => {
        assert.equal(core.computeResultFingerprint({ ok: true, web_detail: { best_guess: 'tokyo tower' } }, 'web'), 'tokyo tower');
        assert.equal(core.computeResultFingerprint({ ok: true }, 'web'), null);
    });

    test('ラベルモードは判定と理由を使う', () => {
        const result = { ok: true, label_detected: true, label_reason: '文字あり' };
        assert.equal(core.computeResultFingerprint(result, 'label'), 'label:true:文字あり');
    });
});

describe('isValidResult（表示する結果の判定）', () => {
    test('テキスト系モードは5文字未満を除く', () => {
        assert.equal(core.isValidResult({ label: 'abcd' }, 'text'), false);
        assert.equal(core.isValidResult({ label: 'abcde' }, 'text'), true);
    });

    test('テキスト系モードは URL を除く', () => {
        assert.equal(core.isValidResult({ label: 'www.example.com' }, 'text'), false);
        assert.equal(core.isValidResult({ label: 'https://example.com' }, 'text'), false);
    });

    test('スコア付きのモード（物体・顔・ロゴ）は短くても残し、空だけ除く', () => {
        for (const mode of ['object', 'face', 'logo']) {
            assert.equal(core.isValidResult({ label: 'Cup' }, mode), true, mode);
            assert.equal(core.isValidResult({ label: ' ' }, mode), false, mode);
        }
    });
});
