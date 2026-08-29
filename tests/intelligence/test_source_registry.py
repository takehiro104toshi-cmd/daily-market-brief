"""source_feeds.yaml v3.0.0（Phase 1-B Source Registry）の整合性検証。

検証観点（P1-B指示）:
- id一意・語彙（state/method/value/role/category/tier/format/auth/usage）の妥当性
- HISTORICALLY_OBSERVED ≠ CURRENTLY_HEALTHY（過去実績と現在死活の分離）
- DEAD判定の根拠・代替の明示 / 重複グループ / CORE要件
- 認証はenum記録のみ（Secret値なし）
- ドメインモデル（SourceEndpoint/SourceHealthObservation）とのroundtrip
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.intelligence.core import serialization
from src.intelligence.sources.model import (
    AuthType,
    FeedFormat,
    HealthState,
    SourceCategory,
    SourceEndpoint,
    SourceHealthObservation,
    UsageStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / "knowledge" / "source_reliability" / "source_feeds.yaml"

CATEGORY_TO_TIER = {
    "primary_official": 1,
    "high_quality_secondary": 2,
    "market_data_provider": 2,
    "general_secondary": 3,
    "other": 3,
}
ALLOWED_METHOD = {"live_http", "legacy_ci_report", "tank_shards", "static_analysis", "live_check_blocked"}
ALLOWED_VALUE = {"MARKET_CRITICAL", "HIGH", "MEDIUM", "LOW"}
ALLOWED_ROLE = {"CORE", "SUPPORT", "CONTEXT", "DISABLE"}


@pytest.fixture(scope="module")
def catalog() -> dict:
    with CATALOG.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def feeds(catalog: dict) -> list[dict]:
    return catalog["feeds"]


def test_version_and_size(catalog: dict, feeds: list[dict]) -> None:
    assert catalog["version"] == "3.0.0"
    assert len(feeds) == 86, "v2の86ソースを欠落なく引き継ぐ"


def test_ids_unique(feeds: list[dict]) -> None:
    ids = [f["id"] for f in feeds]
    assert len(ids) == len(set(ids))


def test_vocabulary_matches_domain_enums(feeds: list[dict]) -> None:
    """カタログの語彙はPythonドメインenumのvalueと一致する（二重定義の乖離防止）。"""
    for f in feeds:
        HealthState(f["current_health"]["state"])
        SourceCategory(f["category"])
        FeedFormat(f["endpoint"]["declared_format"])
        AuthType(f["endpoint"]["auth_type"])
        UsageStatus(f["endpoint"]["usage_status"])
        assert f["current_health"]["method"] in ALLOWED_METHOD, f["id"]
        assert f["investment_value"] in ALLOWED_VALUE, f["id"]
        assert f["role"] in ALLOWED_ROLE, f["id"]


def test_category_tier_mapping(feeds: list[dict]) -> None:
    for f in feeds:
        assert f["tier"] == CATEGORY_TO_TIER[f["category"]], (
            f"{f['id']}: category={f['category']} なら tier={CATEGORY_TO_TIER[f['category']]}"
        )


def test_historical_evidence_never_justifies_current_health(feeds: list[dict]) -> None:
    """HISTORICALLY_OBSERVED ≠ CURRENTLY_HEALTHY。

    healthy判定はcurrentなevidence（live_http / legacy_ci_report）のみが根拠になれる。
    tank実績（6〜7月）だけのソースはunverifiedに留まること。
    """
    for f in feeds:
        ch = f["current_health"]
        if ch["state"] == "healthy":
            assert ch["method"] in ("live_http", "legacy_ci_report"), (
                f"{f['id']}: healthyの根拠が過去実績になっている（method={ch['method']}）"
            )
            if ch["method"] == "legacy_ci_report":
                rc = f.get("recent_ci")
                assert rc and rc["days_failed"] == 0, f"{f['id']}: CI実測の裏付けが必要"
        # tank実績が豊富でも、currentなevidenceが無ければhealthyを名乗らない
        observed = (f["historical"].get("articles_observed") or {}).get("count", 0)
        if observed > 0 and "recent_ci" not in f:
            assert ch["state"] in ("unverified", "auth_required"), (
                f"{f['id']}: tank実績のみでcurrent state={ch['state']} は不可"
            )


def test_historical_and_ci_windows_are_distinct(feeds: list[dict]) -> None:
    for f in feeds:
        window = (f["historical"].get("articles_observed") or {}).get("window")
        rc = f.get("recent_ci")
        if window and rc:
            assert window != rc["window"], f"{f['id']}: 実績窓とCI窓が混同されている"
        if rc:
            assert rc["days_observed"] > 0
            assert 0 <= rc["days_failed"] <= rc["days_observed"]


def test_dead_sources_have_evidence_and_replacement(feeds: list[dict]) -> None:
    dead = [f for f in feeds if f["current_health"]["state"] == "dead"]
    assert dead, "本監査ではDEADが検出されているはず（reuters系・nikkei）"
    for f in dead:
        assert f["current_health"]["note"], f"{f['id']}: DEADは根拠noteが必須"
        assert f["role"] == "DISABLE", f"{f['id']}: DEADはDISABLE"
        assert f.get("replacement_source"), f"{f['id']}: DEADは代替ソースを明示"
        rc = f.get("recent_ci")
        if rc:
            assert rc["days_failed"] == rc["days_observed"], f"{f['id']}: DEADのCI実測は全滅のはず"


def test_duplicate_groups_are_consistent(feeds: list[dict]) -> None:
    by_id = {f["id"]: f for f in feeds}
    groups: dict[str, list[dict]] = {}
    for f in feeds:
        g = f.get("duplicate_group")
        if g:
            groups.setdefault(g, []).append(f)
    assert groups, "重複グループが定義されていること（reuters/boj/mof/ecb/bls等）"
    for g, members in groups.items():
        assert len(members) >= 2, f"group {g}: 2件未満はグループにしない"
        cores = [m["id"] for m in members if m["role"] == "CORE"]
        assert len(cores) <= 1, f"group {g}: COREは高々1件（実際: {cores}）"
        # shadow（replacement_sourceが同グループ内を指すDISABLE）はprimaryへ解決できる
        for m in members:
            rep = m.get("replacement_source")
            if m["role"] == "DISABLE" and rep and rep in by_id:
                target = by_id[rep]
                if target.get("duplicate_group") == g:
                    assert target["role"] != "DISABLE", (
                        f"group {g}: shadow {m['id']} の代替 {rep} もDISABLE"
                    )


def test_core_requirements(feeds: list[dict]) -> None:
    cores = [f for f in feeds if f["role"] == "CORE"]
    assert 5 <= len(cores) <= 15, f"CORE数が運用想定外: {len(cores)}"
    for f in cores:
        ch = f["current_health"]
        assert ch["state"] != "dead", f"{f['id']}: CORE∧DEADは禁止"
        assert f["investment_value"] == "MARKET_CRITICAL", f"{f['id']}: COREはMARKET_CRITICALのみ"
        assert not f.get("replacement_source"), f"{f['id']}: shadowはCOREになれない"
        if ch["state"] != "healthy":
            assert ch["note"], f"{f['id']}: 非healthyのCOREは状態noteが必須"


def test_auth_metadata_is_enum_only_no_secrets(feeds: list[dict]) -> None:
    secret_patterns = [r"Subscription-Key=", r"appId=", r"[?&](api_?key|token|key)=", r"Bearer\s+\w"]
    for f in feeds:
        url = f["endpoint"]["url"]
        for pat in secret_patterns:
            assert not re.search(pat, url, re.IGNORECASE), f"{f['id']}: URLに資格情報の痕跡"
        if f["current_health"]["state"] == "auth_required":
            assert f["endpoint"]["auth_type"] != "none", f"{f['id']}: auth_requiredなのにauth_type=none"


def test_catalog_entry_roundtrips_through_domain_model(feeds: list[dict]) -> None:
    """カタログ→ドメインモデル→serialization roundtripが成立する。"""
    serialization.register_domain_types()
    now = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
    for f in feeds[:10] + [f for f in feeds if f["id"] in ("edinet_disclosures", "nikkei")]:
        ep = SourceEndpoint(
            source_id=f["id"],
            url=f["endpoint"]["url"],
            declared_format=FeedFormat(f["endpoint"]["declared_format"]),
            auth_type=AuthType(f["endpoint"]["auth_type"]),
            usage_status=UsageStatus(f["endpoint"]["usage_status"]),
        )
        obs = SourceHealthObservation(
            health_obs_id=f"shealth_TEST{f['id']}",
            source_id=f["id"],
            checked_at=now,
            state=HealthState(f["current_health"]["state"]),
            method=f["current_health"]["method"],
            note=f["current_health"]["note"] or "",
        )
        assert serialization.decode(serialization.encode(ep)) == ep
        assert serialization.decode(serialization.encode(obs)) == obs


def test_roles_cover_all_feeds_and_disable_reasons(feeds: list[dict]) -> None:
    for f in feeds:
        if f["role"] == "DISABLE":
            ch = f["current_health"]
            reason = (
                ch["state"] == "dead"
                or bool(f.get("replacement_source"))
                or (f["investment_value"] == "LOW" and ch["state"] != "healthy")
            )
            assert reason, f"{f['id']}: DISABLEの根拠（dead/shadow/low×非healthy）がない"
