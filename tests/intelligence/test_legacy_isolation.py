"""LEGACY/PROBEコードの隔離ガード（PROJECT-WIDE RETROACTIVE AUDIT）。

目的:
- J-Quants **V1**（2026-06-01終了）が current production path から到達不能で
  あり続けること。historical referenceとしては残すが、誤って再配線されたら
  ここで落ちる。
- 一時的なdiscovery/probeモジュールがproduction pathへ混ざらないこと。
- 全MarketDataProviderが「symbol未定義」を例外ではなくGAPとして返すこと
  （V1でTypeErrorになっていた欠陥のリグレッション）。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from src.intelligence.market.jquants_topix import JQuantsTopixProvider
from src.intelligence.market.jquants_v2 import (
    JQUANTS_V2_BASE,
    JQuantsV2TopixProvider,
)
from src.intelligence.market.mof_jgb import MofJgbYieldProvider
from src.intelligence.market.series_catalog import load_catalog
from src.intelligence.market.treasury_curve import TreasuryParYieldProvider

MARKET_DIR = Path("src/intelligence/market")
CATALOG = load_catalog(Path("knowledge/market_series/core_series.yaml"))
#: providerのsymbolを持たない系列（identityのみ定義）
NO_SYMBOL_SERIES = "index:growth250.close.closing.tokyo"

#: 一時的な調査用モジュール（production pathへ入れない）
PROBE_MODULES = ("p2g_probe", "p2g1_auth_probe", "p2g2_v2_discovery")
#: production配線を担うモジュール
PRODUCTION_MODULES = ("pilot_runner", "backfill", "store", "ingest", "derived",
                      "series_catalog", "providers", "persistence_check")


class _NoNetworkTransport:
    def fetch(self, *args, **kwargs):  # pragma: no cover - 呼ばれたら失敗
        raise AssertionError("no_symbol判定でネットワークへ出てはならない")


def _providers():
    return {
        "jquants_topix(V1 legacy)": JQuantsTopixProvider(
            lambda *a: (200, b"{}"), env={"JQUANTS_ID_TOKEN": "dummy"}),
        "jquants_v2": JQuantsV2TopixProvider(
            lambda *a: (200, b"{}"), env={"JQUANTS_API_KEY": "dummy"}),
        "treasury_gov": TreasuryParYieldProvider(_NoNetworkTransport()),
        "mof_japan": MofJgbYieldProvider(_NoNetworkTransport()),
    }


class TestNoSymbolContract:
    @pytest.mark.parametrize("name", sorted(_providers()))
    def test_missing_symbol_returns_gap_not_exception(self, name):
        """symbol未定義の系列で例外を投げず `no_symbol` のGAPを返す。"""
        spec = CATALOG.get(NO_SYMBOL_SERIES)
        assert spec is not None
        provider = _providers()[name]
        assert spec.symbol_for(provider.provider_id) is None
        result = provider.fetch_daily_history(spec, start=date(2026, 1, 1),
                                              end=date(2026, 1, 2))
        assert result.error_kind == "no_symbol"
        assert result.url == ""          # 存在しない取得先を記録しない
        assert result.records == ()


class TestLegacyV1Isolation:
    def test_catalog_declares_v2_only(self):
        info = CATALOG.providers["jquants"]
        assert info.api_version == "v2"
        assert info.endpoint_template.startswith(JQUANTS_V2_BASE)
        assert "/v1/" not in info.endpoint_template

    def test_no_production_module_imports_v1_provider(self):
        """production配線モジュールがV1 providerを取り込んでいない。"""
        offenders = []
        for name in PRODUCTION_MODULES:
            path = MARKET_DIR / f"{name}.py"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"JQuantsTopixProvider|from \.jquants_topix import", text):
                offenders.append(name)
        assert offenders == [], f"V1 providerがproduction pathへ再配線されている: {offenders}"

    def test_pilot_runner_wires_v2_provider_for_jquants(self):
        text = (MARKET_DIR / "pilot_runner.py").read_text(encoding="utf-8")
        assert 'JQuantsV2TopixProvider()' in text
        assert 'JQuantsTopixProvider()' not in text

    def test_v1_module_is_marked_legacy(self):
        """V1モジュールの先頭でLEGACY/現行でない旨が宣言されている。"""
        head = (MARKET_DIR / "jquants_topix.py").read_text(encoding="utf-8")[:2000]
        assert "LEGACY" in head
        assert "2026-06-01" in head

    def test_v1_module_still_present_as_historical_evidence(self):
        """歴史的記録として残っていること（削除もまた不整合）。"""
        assert (MARKET_DIR / "jquants_topix.py").exists()


class TestProbeIsolation:
    def test_probe_modules_are_not_referenced_by_production(self):
        offenders = []
        for name in PRODUCTION_MODULES:
            path = MARKET_DIR / f"{name}.py"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            offenders += [f"{name}->{probe}" for probe in PROBE_MODULES if probe in text]
        assert offenders == [], f"probeモジュールがproduction pathから参照されている: {offenders}"

    def test_pilot_workflow_injects_only_the_v2_credential(self):
        """必要最小限のsecretのみ注入する（V1時代のenv名を残さない）。"""
        workflow = Path(".github/workflows/p2d-market-pilot.yml").read_text(encoding="utf-8")
        injected = set(re.findall(r"secrets\.([A-Z_]+)", workflow))
        assert injected == {"JQUANTS_API_KEY"}, (
            f"pilot workflowが注入するsecretが想定と異なる: {sorted(injected)}")
        for legacy in ("JQUANTS_ID_TOKEN", "JQUANTS_REFRESH_TOKEN",
                       "JQUANTS_MAIL", "JQUANTS_PASSWORD"):
            assert legacy not in workflow, f"V1時代のcredential参照が残っている: {legacy}"

    def test_probe_modules_are_not_wired_into_workflows(self):
        workflow = Path(".github/workflows/p2d-market-pilot.yml").read_text(encoding="utf-8")
        run_lines = [ln for ln in workflow.splitlines() if ln.strip().startswith("run:")]
        wired = [p for p in PROBE_MODULES if any(p in ln for ln in run_lines)]
        assert wired == [], f"不要になったprobeがworkflowで実行されている: {wired}"


class TestDocumentationMatchesCatalog:
    """docsがcatalog/implementationより古い状態を禁止する（§13/§17）。

    「documentationを先にPASSへ書き換え、コードを後から合わせる」運用の逆——
    catalogを正として、docsの記述が矛盾していないことだけを検査する。
    """

    CRITICAL = {
        "index:topix.close.closing.tokyo": "jquants",
        "rates:JGB10Y.yield.closing.tokyo": "mof_japan",
        "rates:UST2Y_par.yield.closing.us": "treasury_gov",
    }

    def test_source_mapping_doc_lists_current_preferred_source(self):
        doc = Path("docs/databank/MARKET_SOURCE_MAPPING.md").read_text(encoding="utf-8")
        for series_id, expected in self.CRITICAL.items():
            assert CATALOG.get(series_id).preferred_source == expected
            row = [ln for ln in doc.splitlines() if ln.startswith(f"| {series_id}")]
            assert row, f"{series_id} の行がsymbol対応表に無い"
            assert expected in row[0], (
                f"docsのpreferred sourceがcatalogと矛盾: {series_id} -> {row[0]!r}")

    def test_catalog_spec_does_not_hardcode_a_stale_version(self):
        """spec側にカタログ版数を焼き込まない（乖離の再発防止）。"""
        doc = Path("docs/databank/MARKET_SERIES_CATALOG_SPEC.md").read_text(encoding="utf-8")
        stale = re.findall(r"versioned config・v(\d+\.\d+\.\d+)", doc)
        assert stale == [], f"specにカタログ版数が焼き込まれている: {stale}"

    def test_docs_do_not_present_v1_as_the_current_jquants_api(self):
        """V1を「現行API」として提示しているdocsが無い（歴史的記録は注記付きで可）。"""
        offenders = []
        for path in Path("docs").rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if "api.jquants.com/v1" not in text and "/v1/indices/topix" not in text:
                continue
            # V1に触れるなら、EOL/LEGACY/HISTORICALのいずれかの注記が必要
            if not any(k in text for k in ("2026-06-01", "LEGACY", "HISTORICAL",
                                           "SUPERSEDE", "旧ルート")):
                offenders.append(str(path))
        assert offenders == [], f"V1を現行仕様として記載したdocs: {offenders}"

