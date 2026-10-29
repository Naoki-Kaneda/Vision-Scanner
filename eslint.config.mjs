// static/ の JS を検査する ESLint の設定（npm run lint）
import js from '@eslint/js';
import globals from 'globals';

export default [
    js.configs.recommended,
    {
        files: ['static/**/*.js'],
        languageOptions: {
            ecmaVersion: 2022,
            // import/export を使わない通常のスクリプト（<script src> で読み込む）
            sourceType: 'script',
            globals: globals.browser,
        },
    },
    {
        // static/ の JS の単体テスト（node --test で実行）
        files: ['tests/js/**/*.js'],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: 'commonjs',
            globals: globals.node,
        },
    },
];
