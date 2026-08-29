"""vNext抽象契約（Protocol）。schema 0.2.0（Phase 1-A更新）。

設計方針:
- ストレージ（Evidence/Market/News/Knowledge）と外部性（Clock/LLM）をProtocolで
  抽象化し、各エンジンを注入可能・単体テスト可能にする。
- LLMProviderは特定ベンダーに固定しない。core層はベンダーSDKを一切importせず、
  実装（Anthropic / OpenAI / ローカル等のラッパー）は将来の別パッケージが提供する。
  provider/model名は実行metadata（LLMResult）として保持するだけで、
  domain modelはproviderへ依存しない。
- 参照実装: evidence/jsonl_store.py（EvidenceRepository＋MarketRepositoryを充足）。
  将来Postgres等へ移行してもこの契約とdomain層は変えない。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Protocol, Sequence, runtime_checkable

from .types import LLMResult

if TYPE_CHECKING:  # 型参照のみ（実行時循環importを避ける）
    from ..evidence.model import EvidenceLink, Statement
    from ..market.model import Observation
    from ..sources.model import SourceDocument


@runtime_checkable
class Clock(Protocol):
    """時刻の供給源。テストでは固定時刻を注入する。"""

    def now(self) -> datetime:
        """タイムゾーン付き現在時刻を返す。"""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """ベンダー中立のLLM境界。

    実装要件:
    - 利用不可（キー未設定・SDK未導入・障害）のとき is_available() が False を返し、
      呼び出し側はルールベースのフォールバックを使う。
    - complete() はEvidence参照付きの文章化・抽出にのみ使い、事実・数値の創作をしない。
    """

    def is_available(self) -> bool:
        ...

    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 1024) -> LLMResult:
        ...


@runtime_checkable
class EvidenceRepository(Protocol):
    """Evidence（文書・言明・リンク）の永続化境界。追記のみ・上書きしない。

    重複ID規約: 同一内容→冪等スキップ / 異なる内容→エラー（改定はrevision_ofで新ID）。
    """

    def add_documents(self, docs: Iterable["SourceDocument"]) -> int:
        ...

    def add_statements(self, statements: Iterable["Statement"]) -> int:
        ...

    def add_links(self, links: Iterable["EvidenceLink"]) -> int:
        ...

    def get_document(self, document_id: str) -> Optional["SourceDocument"]:
        ...

    def statements_on(self, day: date) -> Sequence["Statement"]:
        """dayはUTC暦日として解釈する（created_at/event_timeのUTC日付でマッチ）。"""
        ...

    def links_for(self, claim_id: str) -> Sequence["EvidenceLink"]:
        ...


@runtime_checkable
class MarketRepository(Protocol):
    """観測値時系列の永続化境界（Phase 2 market storeの契約）。"""

    def record(self, observations: Iterable["Observation"]) -> int:
        ...

    def series(
        self, entity_id: str, metric: str, start: date, end: date
    ) -> Sequence["Observation"]:
        ...


@runtime_checkable
class NewsRepository(Protocol):
    """構造化ニュース（News Bank）の永続化境界。

    正式なNewsItemスキーマはPhase 2で確定する（tank記事モデル約70フィールドが出発点）。
    それまでの暫定契約としてMappingを受け渡す。
    """

    def save_items(self, items: Sequence[Mapping[str, object]]) -> int:
        ...

    def items_for(self, day: date) -> Sequence[Mapping[str, object]]:
        ...


@runtime_checkable
class KnowledgeRepository(Protocol):
    """knowledge/ 配下の宣言的知識資産への読み取り境界（書き込みはしない）。"""

    def list_assets(self) -> Sequence[str]:
        ...

    def load(self, asset_id: str) -> Mapping[str, object]:
        ...
