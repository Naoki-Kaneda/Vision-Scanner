"""
PIIマスキングユーティリティのテスト。
"""

from pii_mask import mask_pii


class TestPhoneNumberMasking:
    """電話番号のマスキングテスト。"""

    def test_携帯電話番号をマスクする(self):
        assert mask_pii("電話: 090-1234-5678") == "電話: 090-****-****"

    def test_ハイフンなし携帯番号をマスクする(self):
        assert mask_pii("09012345678") == "090-****-****"

    def test_080番号をマスクする(self):
        assert mask_pii("080-9876-5432") == "080-****-****"

    def test_070番号をマスクする(self):
        assert mask_pii("070-1111-2222") == "070-****-****"

    def test_固定電話番号をマスクする(self):
        result = mask_pii("TEL: 03-1234-5678")
        assert "****" in result
        assert "5678" not in result

    def test_国際形式をマスクする(self):
        result = mask_pii("+81-90-1234-5678")
        assert "****" in result


class TestEmailMasking:
    """メールアドレスのマスキングテスト。"""

    def test_メールアドレスをマスクする(self):
        result = mask_pii("連絡先: user@example.com")
        assert "user@" not in result
        assert "example.com" in result
        assert "u***@example.com" in result

    def test_ドット付きメールをマスクする(self):
        result = mask_pii("first.last@company.co.jp")
        assert "first.last@" not in result
        assert "company.co.jp" in result


class TestCreditCardMasking:
    """クレジットカード風番号のマスキングテスト。"""

    def test_ハイフン区切りカード番号をマスクする(self):
        result = mask_pii("カード: 1234-5678-9012-3456")
        assert result == "カード: ****-****-****-3456"

    def test_スペース区切りカード番号をマスクする(self):
        result = mask_pii("1234 5678 9012 3456")
        assert result == "****-****-****-3456"


class TestEdgeCases:
    """境界値テスト。"""

    def test_Noneを渡すとNoneが返る(self):
        assert mask_pii(None) is None

    def test_空文字列を渡すと空文字列が返る(self):
        assert mask_pii("") == ""

    def test_PIIなしのテキストは変更されない(self):
        text = "本日は晴天なり。Vision AI Scannerのテスト。"
        assert mask_pii(text) == text

    def test_整数を渡すとそのまま返る(self):
        assert mask_pii(42) == 42

    def test_複数のPII情報を同時にマスクする(self):
        text = "名前: 太郎, 電話: 090-1234-5678, メール: taro@test.com"
        result = mask_pii(text)
        assert "1234-5678" not in result
        assert "taro@" not in result
