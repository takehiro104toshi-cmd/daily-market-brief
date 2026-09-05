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
    from ..databank.news_model import ArticleIdentity, NewsItem
    from ..databank.query import NewsQuery
    from ..evidence.model import EvidenceLink, Statement
    from ..evidence_qa.model import EvidenceAssessment
    from ..ingestion.model import FetchAttempt
    from ..market.model import Observation
    from ..normalization.model import NormalizationEvent
    from ..sources.model import RawItem, SourceDocument


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
    """News Bank（Phase 2-A正式化。Stage 1の暫定Mapping契約を置換）。

    検索条件はdatabank/query.NewsQuery。実装参照: databank/sqlite_index.py
    （JSONL正本から再構築可能なSQLite索引）。
    """

    def add_news_items(self, items: Sequence["NewsItem"]) -> int:
        ...

    def get_news_item(self, news_item_id: str) -> Optional["NewsItem"]:
        ...

    def search_news(self, query: "NewsQuery") -> Sequence["NewsItem"]:
        ...


@runtime_checkable
class ArticleIdentityRepository(Protocol):
    """Article identity（Phase 2-A設計/P2-B実装）の永続化境界。"""

    def add_identities(self, identities: Sequence["ArticleIdentity"]) -> int:
        ...

    def get_identity(self, article_id: str) -> Optional["ArticleIdentity"]:
        ...

    def identity_for_document(self, source_document_id: str) -> Optional["ArticleIdentity"]:
        ...


@runtime_checkable
class KnowledgeRepository(Protocol):
    """knowledge/ 配下の宣言的知識資産への読み取り境界（書き込みはしない）。"""

    def list_assets(self) -> Sequence[str]:
        ...

    def load(self, asset_id: str) -> Mapping[str, object]:
        ...


@runtime_checkable
class RawRepository(Protocol):
    """Raw Store（Phase 1-C）の永続化境界。append-only・immutable。

    参照実装: ingestion/raw_store.py JsonlRawRepository（JSONL＋content-addressed blob）。
    将来SQLite/Postgresへ差し替えてもdomain/fetcherは無変更。
    """

    def store_body(self, body: bytes) -> tuple:  # (content_hash, locator, created)
        ...

    def add_raw_item(self, item: "RawItem") -> bool:  # 冪等: 同一ID＋同一内容はFalse
        ...

    def get_raw_item(self, raw_item_id: str) -> Optional["RawItem"]:
        ...

    def read_body(self, item: "RawItem") -> bytes:  # metadata→body lookup
        ...

    def iter_raw_items(self) -> Iterable["RawItem"]:
        ...


@runtime_checkable
class FetchAttemptRepository(Protocol):
    """取得試行（FetchAttempt）の時系列記録境界。

    304・timeout・403等でRawItemが生まれない試行も必ず記録する。
    条件付きGETのvalidatorは観測列から導出する（二重保存しない）。
    """

    def add_attempt(self, attempt: "FetchAttempt") -> bool:
        ...

    def iter_attempts(self) -> Iterable["FetchAttempt"]:
        ...

    def attempts_for(self, source_id: str) -> Sequence["FetchAttempt"]:
        ...

    def latest_conditional(self, endpoint_id: str) -> tuple:  # (etag, last_modified)
        ...


@runtime_checkable
class SourceDocumentRepository(Protocol):
    """正規化済み文書（Phase 1-D）の永続化境界。append-only・immutable。

    参照実装: normalization/store.py JsonlNormalizedStore。
    """

    def add_documents(self, documents: Sequence["SourceDocument"]) -> int:
        ...

    def get_document(self, source_document_id: str) -> Optional["SourceDocument"]:
        ...

    def iter_documents(self) -> Iterable["SourceDocument"]:
        ...

    def documents_for_raw_item(self, raw_item_id: str) -> Sequence["SourceDocument"]:
        ...


@runtime_checkable
class ObservationRepository(Protocol):
    """正規化済み数値観測の永続化境界（P1-D）。"""

    def add_observations(self, observations: Sequence["Observation"]) -> int:
        ...

    def get_observation(self, observation_id: str) -> Optional["Observation"]:
        ...

    def iter_observations(self) -> Iterable["Observation"]:
        ...


@runtime_checkable
class NormalizationEventRepository(Protocol):
    """正規化処理イベント（processing event）の時系列記録境界。

    record content（SourceDocument/Observation）と処理時刻を分離するための置き場。
    """

    def add_event(self, event: "NormalizationEvent") -> bool:
        ...

    def iter_events(self) -> Iterable["NormalizationEvent"]:
        ...

    def events_for_raw_item(self, raw_item_id: str) -> Sequence["NormalizationEvent"]:
        ...


@runtime_checkable
class EvidenceAssessmentRepository(Protocol):
    """Evidence QA評価（Phase 1-E）の永続化境界。append-only（上書き禁止）。

    「現在の判定」は履歴からの導出（latest_for）。旧policy versionの評価も保存され続ける。
    """

    def add_assessment(self, assessment: "EvidenceAssessment") -> bool:
        ...

    def iter_assessments(self) -> Iterable["EvidenceAssessment"]:
        ...

    def assessments_for(self, record_id: str) -> Sequence["EvidenceAssessment"]:
        ...

    def latest_for(self, record_id: str, policy_name: Optional[str] = None) -> Optional["EvidenceAssessment"]:
        ...
