"""v3.4 One-Tap Report Generation をネットワークなしで検証する。

対象: ①ワンタップボタンの表示条件（realtime.enabled + endpoint_url） ②POST用JSの
存在とエンドポイント埋め込み ③成功/失敗メッセージ ④連打防止（60秒無効化）
⑤GitHub Token/Secret文字列がHTMLに含まれない ⑥既存の手動Actions導線が残る
⑦Cloudflare Workerコードにtoken直書きが無い（envからのみ参照）。
"""
from datetime import datetime
from pathlib import Path

from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

ACTIONS_URL = "https://github.com/example/daily-market-brief/actions/workflows/daily-market-brief.yml"
ENDPOINT = "https://daily-market-brief-trigger.example.workers.dev/trigger"
WORKER_JS = Path(__file__).resolve().parent.parent / "cloudflare" / "trigger-report-worker.js"


def _report(realtime=None, actions_url=ACTIONS_URL):
    return build_html_report(
        report_date=datetime(2026, 7, 7, 9, 0),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
        actions_url=actions_url,
        realtime=realtime,
    )


# ---------- ① 表示条件 ----------

def test_one_tap_absent_when_realtime_disabled():
    assert "id='one-tap-btn'" not in _report(realtime={"enabled": False, "endpoint_url": ENDPOINT})
    assert "id='one-tap-btn'" not in _report(realtime=None)


def test_one_tap_absent_when_enabled_but_no_endpoint():
    assert "id='one-tap-btn'" not in _report(realtime={"enabled": True, "endpoint_url": ""})


def test_one_tap_present_when_enabled_with_endpoint():
    report = _report(realtime={"enabled": True, "provider": "cloudflare_worker", "endpoint_url": ENDPOINT, "mode": "one_tap"})
    assert "id='one-tap-btn'" in report
    assert "🚀 ワンタップで最新レポート生成" in report
    # エンドポイントURLはdata属性として埋め込まれる（POST先）
    assert f"data-endpoint='{ENDPOINT}'" in report


# ---------- ②③④ JS挙動（POST・メッセージ・連打防止） ----------

def test_js_posts_to_endpoint_with_success_and_error_messages():
    report = _report(realtime={"enabled": True, "endpoint_url": ENDPOINT})
    assert "fetch(endpoint" in report
    assert "method: 'POST'" in report
    assert "生成を開始しました。1〜3分後にページを再読み込みしてください。" in report  # 成功
    assert "生成リクエストに失敗しました" in report                                    # 失敗
    assert "60000" in report                                                          # 60秒連打防止


# ---------- ⑤ セキュリティ ----------

def test_no_token_or_secret_strings_in_html_when_one_tap_enabled():
    report = _report(realtime={"enabled": True, "endpoint_url": ENDPOINT})
    low = report.lower()
    assert "token" not in low
    assert "secret" not in low
    assert "ghp_" not in report
    assert "github_pat" not in low
    assert "ANTHROPIC_API_KEY" not in report
    assert report.count("<div") == report.count("</div>")


# ---------- ⑥ 既存の手動導線が残る ----------

def test_manual_actions_and_reload_still_present_with_one_tap():
    report = _report(realtime={"enabled": True, "endpoint_url": ENDPOINT})
    assert "ページを再読み込み" in report               # 再読み込み
    assert 'class="regenerate-btn"' in report           # GitHub Actionsを開く
    assert ACTIONS_URL in report
    assert "スマホでの実行手順" in report               # スマホ手順


# ---------- ⑦ Cloudflare Worker コード ----------

def test_worker_file_exists():
    assert WORKER_JS.exists()


def test_worker_has_no_hardcoded_token():
    src = WORKER_JS.read_text(encoding="utf-8")
    # env 経由でのみ参照していること（env.GITHUB_TOKEN）
    assert "env.GITHUB_TOKEN" in src
    # 実トークンらしき直書きが無いこと
    assert "ghp_" not in src
    assert "github_pat_" not in src
    # "GITHUB_TOKEN = " のような代入（直書き）が無いこと
    assert "GITHUB_TOKEN=" not in src.replace(" ", "")


def test_worker_dispatches_workflow_and_restricts_cors():
    src = WORKER_JS.read_text(encoding="utf-8")
    assert "/dispatches" in src                       # workflow_dispatch API
    assert "workflow dispatched" in src               # 成功レスポンス
    assert "Access-Control-Allow-Origin" in src       # CORS制御
    assert "ALLOWED_ORIGIN" in src                    # 許可Origin設定
    assert "/trigger" in src                          # POST /trigger


def test_worker_success_and_failure_response_shape():
    src = WORKER_JS.read_text(encoding="utf-8")
    assert '"ok": true' in src or "ok: true" in src
    assert '"ok": false' in src or "ok: false" in src
