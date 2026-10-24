"""P11-A3 — browser の test（Playwright は任意の dev の道具。無ければ skip。loopback の server だけ ・外へは出ない）。

shell の load ・service worker の登録と precache の中身 ・空の欄 ・明示の時点の要求 ・描画 ・MUTE ／ 除外の可視 ・DOM に id なし ・
localStorage ／ IndexedDB ／ Cache Storage に private な値なし ・offline の shell ・offline で private な data なし ・失敗で前の DOM が
消える ・CSP が inline の script を止める。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.intelligence.personal_intelligence.attention_model import AttentionState, AttentionTargetKind
from src.intelligence.personal_intelligence.decisions import AttentionCreate
from src.intelligence.personal_intelligence.executor import apply_decision
from src.intelligence.personal_ui.local_server import LocalServer
from tests.intelligence.phase11_runtime_registry import P11_SHELL_CACHE_NAME, P11_SHELL_PRECACHE
from tests.intelligence.test_personal_ui_server import AS_OF, AT, AUTHOR, HOUR, T0, world  # noqa: F401 - fixture

sync_api = pytest.importorskip("playwright.sync_api")
CHROMIUM_CANDIDATES = tuple(p for p in (os.environ.get("P11_TEST_CHROMIUM", ""),
                                        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome") if p)


def _launch(playwright):
    try:
        return playwright.chromium.launch()
    except Exception:  # noqa: BLE001 - fall back to the preinstalled build; skip when none works
        for candidate in CHROMIUM_CANDIDATES:
            if Path(candidate).is_file():
                try:
                    return playwright.chromium.launch(executable_path=candidate)
                except Exception:  # noqa: BLE001
                    continue
    pytest.skip("no launchable Chromium for Playwright")


@pytest.fixture
def browser_app(world):
    events: list = []
    apply_decision(AttentionCreate(target_kind=AttentionTargetKind.P9_THESIS, target_root_id=world["p9"]["t1"].thesis_id,
                                   observed_p9_revision_id=world["p9"]["t1"].revision_id, state=AttentionState.MUTE,
                                   author_ref=AUTHOR, reviewed_at=T0 + 5 * HOUR), p10_root=world["p10"],
                   p9_root=world["p9"]["root"])                                              # MUTE の行が見えることを確かめる
    srv = LocalServer.start(world["p10"], world["p9"]["root"], port=0, on_event=lambda *e: events.append(e))
    srv.start_in_thread()
    with sync_api.sync_playwright() as playwright:
        browser = _launch(playwright)
        context = browser.new_context()
        page = context.new_page()
        console: list = []
        page.on("console", lambda message: console.append(message.text))
        yield dict(srv=srv, url=srv.app_url, page=page, context=context, events=events, console=console, **world)
        context.close()
        browser.close()
    srv.shutdown()


def _storage_state(page) -> dict:
    return page.evaluate("""async () => {
        const caches_ = {};
        for (const name of await caches.keys()) {
            const cache = await caches.open(name);
            caches_[name] = (await cache.keys()).map((request) => new URL(request.url).pathname).sort();
        }
        const dbs = indexedDB.databases ? (await indexedDB.databases()).map((db) => db.name) : [];
        return { localStorage: Object.keys(localStorage), sessionStorage: Object.keys(sessionStorage),
                 caches: caches_, indexedDB: dbs, cookies: document.cookie };
    }""")


def _api_calls(events: list) -> int:
    return sum(1 for e in events if e[1] == "/api/view")


def test_a_shell_loads_registers_a_shell_only_worker_and_starts_with_empty_fields(browser_app) -> None:
    page = browser_app["page"]
    page.goto(browser_app["url"], wait_until="load")
    assert page.title() == "Personal Intelligence — private local"
    assert "PRIVATE" in page.text_content("#private-indicator")
    assert page.input_value("#at") == "" and page.input_value("#as-of-date") == ""        # 時計の既定は無い
    assert page.evaluate("() => navigator.serviceWorker.ready.then((r) => !!r.active)")
    state = _storage_state(page)
    assert state["caches"] == {P11_SHELL_CACHE_NAME: sorted(P11_SHELL_PRECACHE)}
    assert state["localStorage"] == [] and state["sessionStorage"] == [] and state["indexedDB"] == []
    assert state["cookies"] == ""
    assert _api_calls(browser_app["events"]) == 0                                          # 読み込みは明示だけ
    page.click("#load")                                                                    # 空のまま
    assert "明示に入力" in page.text_content("#message") and _api_calls(browser_app["events"]) == 0
    page.click("#fill-clock")                                                              # 欄を埋めるだけ ・送らない
    assert page.input_value("#at") != "" and page.input_value("#as-of-date") != ""
    assert "送信はしていません" in page.text_content("#message") and _api_calls(browser_app["events"]) == 0
    assert browser_app["console"] == []


def test_b_explicit_pit_renders_the_model_in_order_with_muted_and_excluded_rows_and_no_private_values(browser_app) -> None:
    page = browser_app["page"]
    page.goto(browser_app["url"], wait_until="load")
    page.fill("#at", AT)
    page.fill("#as-of-date", AS_OF)
    page.click("#load")
    page.wait_for_selector("#review-rows tr")
    rows = page.locator("#review-rows tr")
    assert rows.count() == 3 and _api_calls(browser_app["events"]) == 1
    ordinals = [rows.nth(i).locator("td").nth(0).text_content() for i in range(3)]
    assert ordinals == ["0", "1", "2"]                                                     # 応答の順のまま
    attentions = {rows.nth(i).get_attribute("data-attention") for i in range(3)}
    assert attentions == {"FOCUS", "NORMAL", "MUTE"}                                      # MUTE の行も見える
    assert page.locator("#review-rows tr[data-excluded='true']").count() == 1              # 除外の行も見える
    assert "yes" in page.text_content("#profile-list") and "14" in page.text_content("#profile-list")
    assert AS_OF in page.text_content("#as-of")
    body = page.text_content("body")
    for sentinel in browser_app["sentinels"]:
        assert sentinel not in body, sentinel
    state = _storage_state(page)
    assert state["localStorage"] == [] and state["indexedDB"] == [] and state["cookies"] == ""
    assert all("/api/" not in path for paths in state["caches"].values() for path in paths)   # API は Cache Storage に無い
    assert "?" not in page.url and AT not in page.url
    assert browser_app["console"] == []


def test_c_failed_refresh_clears_the_private_dom_and_shows_only_a_safe_code(browser_app) -> None:
    page = browser_app["page"]
    page.goto(browser_app["url"], wait_until="load")
    page.fill("#at", AT)
    page.fill("#as-of-date", AS_OF)
    page.click("#load")
    page.wait_for_selector("#review-rows tr")
    page.fill("#as-of-date", "2026-02-30")                                                 # server が拒む日
    page.click("#load")
    page.wait_for_function("() => document.getElementById('review-rows').children.length === 0")   # 関数の形（CSP は eval を止める）
    assert page.locator("#review").is_hidden() and page.locator("#profile").is_hidden()
    assert "VIEW_INPUT_INVALID:AS_OF_DATE_INVALID" in page.text_content("#message")
    body = page.text_content("body")
    for sentinel in browser_app["sentinels"]:
        assert sentinel not in body, sentinel


def test_d_offline_shell_loads_but_private_data_does_not(browser_app) -> None:
    page, context = browser_app["page"], browser_app["context"]
    page.goto(browser_app["url"], wait_until="load")
    page.evaluate("() => navigator.serviceWorker.ready")
    page.fill("#at", AT)
    page.fill("#as-of-date", AS_OF)
    page.click("#load")
    page.wait_for_selector("#review-rows tr")
    calls_before = _api_calls(browser_app["events"])
    context.set_offline(True)
    page.reload(wait_until="load")                                                          # shell は SW の cache から
    assert page.title() == "Personal Intelligence — private local"
    assert page.locator("#review-rows tr").count() == 0                                     # 前の private な応答は無い
    assert page.locator("#offline").is_visible()
    page.fill("#at", AT)
    page.fill("#as-of-date", AS_OF)
    page.click("#load")
    page.wait_for_function("() => !document.getElementById('message').hidden")
    assert page.locator("#review-rows tr").count() == 0
    assert "private data requires the local server" in page.text_content("#offline")
    assert _api_calls(browser_app["events"]) == calls_before                                # server に届かない
    state = _storage_state(page)
    assert all("/api/" not in path for paths in state["caches"].values() for path in paths)
    assert state["localStorage"] == [] and state["indexedDB"] == []
    context.set_offline(False)


def test_e_csp_blocks_inline_script_execution(browser_app) -> None:
    page = browser_app["page"]
    page.goto(browser_app["url"], wait_until="load")
    violated = page.evaluate("""() => new Promise((resolve) => {
        document.addEventListener('securitypolicyviolation', (event) => resolve(event.violatedDirective), { once: true });
        const script = document.createElement('script');
        script.textContent = 'window.__p11_inline = 1;';
        document.head.appendChild(script);
        setTimeout(() => resolve('none'), 1000);
    })""")
    assert violated.startswith("script-src")
    assert page.evaluate("() => window.__p11_inline") is None
