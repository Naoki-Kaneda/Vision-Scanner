"""
型定義モジュール。
プロジェクト全体で使用する TypedDict とタイプエイリアスを一元管理する。
ファイル名を vision_types.py としているのは、Python標準ライブラリの types および
CPython内部モジュール _types との名前衝突を回避するため。
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from typing import NotRequired, TypedDict
else:
    from typing_extensions import NotRequired, TypedDict


# ─── 座標型 ──────────────────────────────────────
Vertex = list[int | float]
BoundingBox = list[Vertex]


# ─── Vision API data 要素型 ──────────────────────
class TextDataItem(TypedDict):
    """テキスト / 物体 / ロゴ検出の個別データ項目。"""

    label: str
    bounds: BoundingBox


class FaceDataItem(TypedDict):
    """顔検出の個別データ項目。"""

    label: str
    bounds: BoundingBox
    emotions: dict[str, str]
    confidence: float


class ClassifyDataItem(TypedDict):
    """分類タグの個別データ項目。"""

    label: str
    score: float


class WebDataItem(TypedDict):
    """Web検索の個別データ項目（ラベルのみ）。"""

    label: str


# 全モードの data リスト要素の共用体
DataItem = TextDataItem | FaceDataItem | ClassifyDataItem | WebDataItem


# ─── Web検索詳細 ─────────────────────────────────
class WebEntity(TypedDict):
    """Web エンティティ（名前とスコア）。"""

    name: str
    score: float


class WebPage(TypedDict):
    """関連ページ情報。"""

    url: str
    title: str


class WebDetail(TypedDict):
    """Web検索の詳細結果。"""

    best_guess: str | None
    entities: list[WebEntity]
    pages: list[WebPage]
    similar_images: list[str]


# ─── Vision API 統一レスポンス ────────────────────
class VisionSuccessResponse(TypedDict):
    """Vision API 成功レスポンス。"""

    ok: bool
    data: list[DataItem]
    image_size: list[int] | None
    error_code: None
    message: None
    # モードによって省略されるフィールド
    warnings: NotRequired[list[str]]
    label_detected: NotRequired[bool]
    label_reason: NotRequired[str]
    web_detail: NotRequired[WebDetail]


class VisionErrorResponse(TypedDict):
    """Vision API エラーレスポンス。"""

    ok: bool
    data: list[DataItem]
    image_size: None
    error_code: str
    message: str


# 成功 or エラーの共用体
VisionResponse = VisionSuccessResponse | VisionErrorResponse


# ─── レート制限 ──────────────────────────────────
# try_consume の戻り値: (allowed, reason, request_id, limit_type)
ConsumeResult = tuple[bool, str, str | None, str | None]


# ─── プロキシ設定 ────────────────────────────────
class ProxyStatus(TypedDict):
    """プロキシ設定状態。"""

    enabled: bool
    url: str


# ─── 翻訳辞書型 ─────────────────────────────────
TranslationDict = dict[str, str]
