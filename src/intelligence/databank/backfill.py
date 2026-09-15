"""Historical Tank Backfillエンジン（Phase 2-C）。

BACKFILL IS A DATA MIGRATION, NOT A FILE COPY:
    Legacy Article → tank互換Adapter → Normalized SourceDocument
    → HISTORICAL Evidence QA → Article Identity（blocking付き）→ NewsItem
    → Data Bank Validation → canonical JSONL →（後段）SQLite index

保証:
- chunk処理（全件をメモリへ載せない）・checkpoint/resume・冪等（決定論的ID＋
  各storeの冪等add）・reject ledger（黙って捨てない）・入力READ ONLY。
- 存在しないfetch provenanceを捏造しない（FetchAttemptは作らない。migration由来は
  normalizer_name="tank_article"・raw_item_id=""で機械的に区別可能）。
- 新解釈の生成禁止（LLM分類・importance等なし。legacy値はLegacyAnnotation隔離）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from ..core import serialization
from ..core.ids import new_id
from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION, SourceTier
from ..evidence_qa.assess import assess_source_document
from ..evidence_qa.policy import TrustPolicy
from ..evidence_qa.store import JsonlAssessmentStore
from ..normalization.feed_normalizer import SourceMeta
from ..normalization.model import NormalizationStatus
from ..normalization.store import JsonlNormalizedStore
from ..normalization.tank_article_normalizer import (
    NORMALIZER_VERSION as TANK_NORMALIZER_VERSION,
    normalize_tank_article,
)
from .article_store import JsonlArticleStore
from .identity_resolver import ALGORITHM_VERSION
from .identity_runtime import IdentityRuntime
from .news_model import LegacyAnnotation, NewsItem
from .backfill_inventory import InputInventory, iter_records

DEFAULT_CHUNK_SIZE = 250

#: reject ledgerのstage語彙
REJECT_STAGES = ("input", "source_mapping", "normalization", "identity", "news_item",
                 "unexpected")


@dataclass(frozen=True, kw_only=True)
class RejectRecord:
    """移行不能record 1件分（黙って捨てない）。legacy入力自体は変更しない。"""

    run_id: str
    legacy_locator: str  # "shard相対path:行番号"
    legacy_id: str
    stage: str
    reason_codes: Tuple[str, ...]
    exception_type: str = ""
    detail: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.stage not in REJECT_STAGES:
            raise ValueError(f"unknown stage: {self.stage}")


@dataclass(frozen=True, kw_only=True)
class BackfillRun:
    """backfill 1回分のrun manifest（監査履歴。再処理時も旧runは残る）。"""

    run_id: str  # bfr_<ULID>
    started_at: datetime
    completed_at: Optional[datetime] = None
    source_dataset: str = ""
    input_fingerprint: str = ""
    schema_version_used: str = SCHEMA_VERSION
    normalizer_version: str = TANK_NORMALIZER_VERSION
    identity_algorithm_version: str = ALGORITHM_VERSION
    trust_policy: str = ""  # "HISTORICAL:1.0.0"
    records_seen: int = 0
    records_success: int = 0  # QA ACCEPT系まで到達
    records_partial: int = 0  # 正規化PARTIAL
    records_rejected: int = 0  # ledger送り
    records_failed: int = 0  # 想定外例外（ledger送り・stage=unexpected）
    checkpoint: int = 0  # 次に処理するrecord_index
    status: str = "running"  # running / completed / crashed
    limit: int = 0  # 段階実行時の上限（0=全件）
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ensure_aware(self.started_at, "BackfillRun.started_at")


class JsonlNewsBankStore:
    """News Bank canonical JSONL（news_items / legacy_annotations / reject_ledger /
    backfill_runs）。append-only・冪等・crash-safe（他storeと同型）。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        serialization.register_domain_types()
        self._news: Dict[str, NewsItem] = {}
        self._annotations: Dict[str, LegacyAnnotation] = {}
        self._rejects: List[RejectRecord] = []
        self._runs: List[BackfillRun] = []
        self.recovered_lines = 0
        self._load()

    def _file(self, name: str) -> Path:
        return self.root / f"{name}.jsonl"

    def _load(self) -> None:
        sinks = {
            "news_items": lambda o: self._news.__setitem__(o.news_item_id, o),
            "legacy_annotations": lambda o: self._annotations.__setitem__(o.annotation_id, o),
            "reject_ledger": self._rejects.append,
            "backfill_runs": self._runs.append,
        }
        for name, sink in sinks.items():
            path = self._file(name)
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sink(serialization.decode(json.loads(line)))
                    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                        self.recovered_lines += 1

    def _append(self, name: str, obj) -> None:
        with self._file(name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(serialization.encode(obj), ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def add_news_item(self, item: NewsItem) -> bool:
        """news_items.jsonlは追記ログ（同一IDの新versionを追記し、replay時は最新が正）。

        merge進行でprimary/headlineが更新されるため、documentsと違い同一IDの
        内容更新を許す（旧versionもログに残る——破壊的上書きなし）。
        """
        existing = self._news.get(item.news_item_id)
        if existing is not None and serialization.encode(existing) == serialization.encode(item):
            return False  # 冪等
        self._append("news_items", item)
        self._news[item.news_item_id] = item
        return True

    def add_annotation(self, ann: LegacyAnnotation) -> bool:
        if ann.annotation_id in self._annotations:
            return False
        self._append("legacy_annotations", ann)
        self._annotations[ann.annotation_id] = ann
        return True

    def add_reject(self, record: RejectRecord) -> None:
        self._append("reject_ledger", record)
        self._rejects.append(record)

    def add_run(self, run: BackfillRun) -> None:
        self._append("backfill_runs", run)
        self._runs.append(run)

    def get_news_item(self, news_item_id: str) -> Optional[NewsItem]:
        return self._news.get(news_item_id)

    def iter_news_items(self):
        return iter(list(self._news.values()))

    def iter_annotations(self):
        return iter(list(self._annotations.values()))

    def iter_rejects(self) -> Tuple[RejectRecord, ...]:
        return tuple(self._rejects)

    def iter_runs(self) -> Tuple[BackfillRun, ...]:
        return tuple(self._runs)

    def latest_checkpoint(self, input_fingerprint: str) -> int:
        """同一入力に対する再開位置（run manifest履歴からの導出）。"""
        points = [r.checkpoint for r in self._runs
                  if r.input_fingerprint == input_fingerprint]
        return max(points, default=0)


def build_source_mapping(catalog: Mapping[str, object]) -> Dict[str, Tuple[str, int, str]]:
    """legacy source_name → (source_id, tier, confidence)。

    P1-Bカタログはtank configを正として構築したため、name完全一致が主経路
    （実測: 42/42名・3,056/3,056件が一致）。不一致は推測せず
    LEGACY_UNKNOWN_SOURCE表現（legacy_unknown:<domain>）へ落とす。
    """
    mapping: Dict[str, Tuple[str, int, str]] = {}
    for feed in catalog["feeds"]:
        mapping[str(feed["name"])] = (str(feed["id"]), int(feed.get("tier", 3)),
                                      "exact_name")
    return mapping


def map_legacy_source(
    article: Mapping[str, object], mapping: Mapping[str, Tuple[str, int, str]]
) -> Tuple[str, SourceTier, str]:
    name = str(article.get("source_name", ""))
    if name in mapping:
        source_id, tier, confidence = mapping[name]
        return source_id, SourceTier(tier), confidence
    domain = str(article.get("source_domain", "unknown")).replace(".", "_")
    return f"legacy_unknown:{domain}", SourceTier.TIER3, "unmatched"


@dataclass(frozen=True, kw_only=True)
class BackfillStores:
    normalized: JsonlNormalizedStore
    articles: JsonlArticleStore
    qa: JsonlAssessmentStore
    news_bank: JsonlNewsBankStore


def open_stores(root: Path) -> BackfillStores:
    root = Path(root)
    return BackfillStores(
        normalized=JsonlNormalizedStore(root / "normalized"),
        articles=JsonlArticleStore(root / "articles"),
        qa=JsonlAssessmentStore(root / "evidence_qa"),
        news_bank=JsonlNewsBankStore(root / "news"),
    )


class BackfillEngine:
    def __init__(
        self,
        dataset_root: Path,
        stores: BackfillStores,
        policy: TrustPolicy,
        catalog: Mapping[str, object],
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.dataset_root = Path(dataset_root)
        self.stores = stores
        self.policy = policy
        self.mapping = build_source_mapping(catalog)
        self.chunk_size = chunk_size
        self._clock = clock
        self.runtime = IdentityRuntime(stores.articles, clock=clock)
        # resume: 既存canonical文書でin-memory索引を再構築（冪等の前提）
        self.runtime.preload(stores.normalized.iter_documents())

    # ---------------------------------------------------------------- 1 record

    def _process_record(self, run_id: str, locator: str, article) -> str:
        """1 legacy record → 'success' | 'partial' | 'rejected'。例外は呼び出し側。"""
        bank = self.stores.news_bank
        if article is None:
            bank.add_reject(RejectRecord(
                run_id=run_id, legacy_locator=locator, legacy_id="",
                stage="input", reason_codes=("invalid_json",)))
            return "rejected"

        legacy_id = str(article.get("article_id", ""))
        source_id, tier, confidence = map_legacy_source(article, self.mapping)
        meta = SourceMeta(source_id=source_id, tier=tier,
                          publisher=str(article.get("source_name", "")),
                          default_language=str(article.get("language", "")))
        result = normalize_tank_article(article, meta)
        if not result.documents:
            bank.add_reject(RejectRecord(
                run_id=run_id, legacy_locator=locator, legacy_id=legacy_id,
                stage="normalization",
                reason_codes=tuple(i.code for i in result.issues) or ("unknown",)))
            return "rejected"
        doc = result.documents[0]
        self.stores.normalized.add_documents([doc])
        if result.event is not None:
            self.stores.normalized.add_event(result.event)

        # LegacyAnnotation隔離（not ground truth）＋historical import provenance
        ann = LegacyAnnotation.from_tank_article(article, doc.source_document_id)
        ann = LegacyAnnotation(
            annotation_id=ann.annotation_id, target_record_id=ann.target_record_id,
            origin="legacy_tank",
            annotations=ann.annotations + (
                ("legacy_shard_locator", locator),
                ("legacy_article_id", legacy_id),
                ("source_mapping_confidence", confidence),
                ("not_ground_truth", "true"),
            ),
            note=ann.note)
        bank.add_annotation(ann)

        # HISTORICAL Evidence QA（既存文書との横断評価はidentity層の責務のため
        # existing_documents=()——O(n²)回避とrevision/duplication軸の二重評価防止）
        assessment = assess_source_document(
            doc,
            source_info=self._source_info(source_id, tier),
            policy=self.policy,
            reference_time=self._clock(),
        )
        self.stores.qa.add_assessment(assessment)

        # Article Identity（blocking index経由・CANDIDATEはmergeされない）
        ingest = self.runtime.ingest_document(doc)
        if ingest.article is not None:
            news, _links = self.runtime.build_news_item(ingest.article)
            bank.add_news_item(news)

        return "partial" if result.status is NormalizationStatus.PARTIAL else "success"

    def _source_info(self, source_id: str, tier: SourceTier):
        from ..evidence_qa.model import SourceInfo

        return SourceInfo(source_id=source_id, tier=tier)

    # ---------------------------------------------------------------- run

    def run(
        self,
        inventory: InputInventory,
        *,
        limit: int = 0,
        resume: bool = True,
        fail_injector: Optional[Callable[[int], None]] = None,
    ) -> BackfillRun:
        """chunk単位でbackfillを実行する。checkpoint/resume・冪等。

        fail_injector: テスト用（record_indexで例外を注入しcrash recoveryを検証）。
        """
        bank = self.stores.news_bank
        fingerprint = inventory.input_fingerprint
        start_index = bank.latest_checkpoint(fingerprint) if resume else 0
        run_id = new_id("bfr", self._clock())
        seen = success = partial = rejected = failed = 0
        checkpoint = start_index
        status = "completed"

        try:
            chunk_count = 0
            for index, locator, article in iter_records(self.dataset_root):
                if index < start_index:
                    continue
                if limit and index >= limit:
                    break
                if fail_injector is not None:
                    fail_injector(index)
                seen += 1
                try:
                    outcome = self._process_record(run_id, locator, article)
                except Exception as exc:  # noqa: BLE001 想定外もledgerへ（黙って捨てない）
                    bank.add_reject(RejectRecord(
                        run_id=run_id, legacy_locator=locator,
                        legacy_id=str((article or {}).get("article_id", "")),
                        stage="unexpected", reason_codes=("exception",),
                        exception_type=type(exc).__name__, detail=str(exc)[:160]))
                    failed += 1
                else:
                    if outcome == "success":
                        success += 1
                    elif outcome == "partial":
                        partial += 1
                    else:
                        rejected += 1
                checkpoint = index + 1
                chunk_count += 1
                if chunk_count >= self.chunk_size:
                    chunk_count = 0  # chunk境界（manifest追記は最終時。checkpointは値で保持）
        except BaseException:
            status = "crashed"
            raise
        finally:
            run = BackfillRun(
                run_id=run_id, started_at=self._clock(), completed_at=self._clock(),
                source_dataset=str(self.dataset_root),
                input_fingerprint=fingerprint,
                trust_policy=f"{self.policy.name}:{self.policy.version}",
                records_seen=seen, records_success=success, records_partial=partial,
                records_rejected=rejected, records_failed=failed,
                checkpoint=checkpoint, status=status, limit=limit)
            bank.add_run(run)
        return run


def reconcile(run: BackfillRun) -> Tuple[bool, str]:
    """会計検証: seen = success + partial + rejected + failed（loss不明ゼロ）。"""
    accounted = (run.records_success + run.records_partial
                 + run.records_rejected + run.records_failed)
    ok = run.records_seen == accounted
    return ok, (f"seen={run.records_seen} = success={run.records_success} "
                f"+ partial={run.records_partial} + rejected={run.records_rejected} "
                f"+ failed={run.records_failed} → {'OK' if ok else 'MISMATCH'}")
