"""
PIIマスキングユーティリティ。
ログ出力前にテキスト中の個人情報（電話番号、メールアドレス、クレジットカード風番号）をマスクする。
"""

import re

# 電話番号パターン（日本形式: 090-1234-5678, 03-1234-5678, +81-90-1234-5678 等）
_PHONE_PATTERNS = [
    # 携帯: 090/080/070 + ハイフンあり/なし
    re.compile(r'(0[789]0)[- ]?(\d{4})[- ]?(\d{4})'),
    # 固定: 03-1234-5678, 06-1234-5678 等
    re.compile(r'(0\d{1,4})[- ](\d{1,4})[- ](\d{4})'),
    # 国際形式: +81-90-1234-5678
    re.compile(r'(\+\d{1,3})[- ]?(\d{1,4})[- ]?(\d{1,4})[- ]?(\d{4})'),
]

# メールアドレスパターン
_EMAIL_PATTERN = re.compile(
    r'([a-zA-Z0-9._%+\-])[a-zA-Z0-9._%+\-]*@([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})'
)

# クレジットカード風の数字列（4桁×4グループ、ハイフンまたはスペース区切り）
_CARD_PATTERN = re.compile(
    r'(\d{4})[- ](\d{4})[- ](\d{4})[- ](\d{4})'
)

# マイナンバー風の数字列（12桁連続）
_MYNUMBER_PATTERN = re.compile(r'\b(\d{12})\b')


def mask_pii(text: str) -> str:
    """テキスト中のPII情報をマスクする。

    対象:
    - 電話番号: 090-1234-5678 → 090-****-****
    - メールアドレス: user@example.com → u***@example.com
    - クレジットカード風番号: 1234-5678-9012-3456 → ****-****-****-3456
    - 12桁連続数字: 123456789012 → ************

    Args:
        text: マスク対象のテキスト

    Returns:
        マスク済みテキスト
    """
    if not text or not isinstance(text, str):
        return text

    result = text

    # クレジットカード風（先にマッチさせて電話番号パターンとの競合を防ぐ）
    result = _CARD_PATTERN.sub(r'****-****-****-\4', result)

    # マイナンバー風
    result = _MYNUMBER_PATTERN.sub('************', result)

    # 電話番号
    for pattern in _PHONE_PATTERNS:
        result = pattern.sub(
            lambda m: m.group(1) + '-****-****',
            result,
        )

    # メールアドレス
    result = _EMAIL_PATTERN.sub(r'\1***@\2', result)

    return result
