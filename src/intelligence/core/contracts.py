"""vNext抽象契約（Protocol）。Stage 1ではインターフェース定義のみで実装しない。

設計方針:
- ストレージ（Evidence/Market/News/Knowledge）と外部性（Clock/LLM）を
  Protocolで抽象化し、各エンジンを注入可能・単体テスト可能にする
  （docs/rebuild/TARGET_ARCHITECTURE.md §3-4）。
- LLMProviderは特定ベンダーに固定しない。core層はベンダーSDKを一切importせず、
  実装（Anthropic / OpenAI / ローカル等のラッパー）は将来の別パッケージが提供する。
- ここでのメソッドは最小集合。Phase 1〜2で後方互換に拡張する
  （既存メソッドのシグネチャ変更ではなくメソッド追加で行う）。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Mapping, Protocol, Sequence, runtime_checkable

from .types import EvidenceRecord, LLMResult, MarketObservation


@runtime_checkable
class Clock(Protocol):
    """時刻の供給源。テストでは固定時刻を注入する（旧report_scheduleの作法を継承）。"""

    def now(self) -> datetime:
        """タイムゾーン付き現在時刻を返す。"""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """ベンダー中立のLLM境界。

    実装要件（Phase 3のLLM Writer等が前提とする契約）:
    - 利用不可（キー未設定・SDK未導入・障害）のとき is_available() が False を返し、
      呼び出し側はルールベースのフォールバックを使う（旧llm_enhancerの縮退思想を継承）。
    - complete() はEvidence参照付きの文章化にのみ使い、事実・数値の創作をしない。
    """

    def is_available(self) -> bool:
        ...

    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 1024) -> LLMResult:
        ...


@runtime_checkable
class EvidenceRepository(Protocol):
    """Evidenceの永続化境界。全下流機能はここを経由してFACT/ANALYSIS/FORECASTへアクセスする。"""

    def append(self, records: Iterable[EvidenceRecord]) -> int:
        """レコードを追記し、書き込んだ件数を返す（追記のみ・上書きしない）。"""
        ...

    def for_date(self, day: date) -> Sequence[EvidenceRecord]:
        """指定日のEvidenceを返す（無ければ空列）。"""
        ...


@runtime_checkable
class MarketRepository(Protocol):
    """市場時系列の永続化境界（Phase 2 market store）。"""

    def record(self, observations: Iterable[MarketObservation]) -> int:
        ...

    def series(self, metric_id: str, start: date, end: date) -> Sequence[MarketObservation]:
        ...


@runtime_checkable
class NewsRepository(Protocol):
    """構造化ニュース（News Bank）の永続化境界。

    正式なNewsItemスキーマはPhase 2で確定するため、Stage 1では
    Mapping（published_at / source / country / tickers / themes / summary /
    importance 等のキーを想定）を受け渡す暫定契約とする。
    """

    def save_items(self, items: Sequence[Mapping[str, object]]) -> int:
        ...

    def items_for(self, day: date) -> Sequence[Mapping[str, object]]:
        ...


@runtime_checkable
class KnowledgeRepository(Protocol):
    """knowledge/ 配下の宣言的知識資産への読み取り境界（書き込みはしない——知識は人が編集する）。"""

    def list_assets(self) -> Sequence[str]:
        """利用可能な資産ID（各YAMLトップレベルの `id`）の一覧。"""
        ...

    def load(self, asset_id: str) -> Mapping[str, object]:
        """資産IDでパース済み内容を返す。未知のIDは KeyError。"""
        ...
