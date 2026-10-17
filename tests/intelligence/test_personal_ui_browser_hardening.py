"""P11-A4 — browser の硬化の test（Playwright は任意。無ければ skip。loopback だけ）。

敵対的な model の文字列（XSS ・制御文字）は拒まれ実行されない ／ 形の崩れた応答は private な DOM を消す ／ 失敗（停止 ・500 ・503 ・
崩れた JSON ・schema の不一致 ・timeout ・中止 ・不正な時点）で古い行が残らない ／ 時点は URL ・history ・保存に入らず reload で
欄が空 ／ SW の更新は古い p11-shell-* だけ消し他の cache に触れず ・毒の entry は配らない ／ 外部の network ゼロ ・console 空 ・
cookie 空 ／ 保存の証明（各段階）／ accessibility の smoke ・keyboard の送信。
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from tests.intelligence.phase11_runtime_registry import P11_SHELL_CACHE_NAME, P11_SHELL_PRECACHE, PHASE11_STATIC_DIR
from tests.intelligence.test_personal_ui_browser import _api_calls, _storage_state, browser_app  # noqa: F401 - fixture
from tests.intelligence.test_personal_ui_server import AS_OF, AT, GOOD, NOTE, body_json, request, world  # noqa: F401

pytest.importorskip("playwright.sync_api")
REPO_ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "SENTINEL-A4-BROWSER"
HOSTILE = ("<script>window.__xss=1</script>", "<img src=x onerror=\"window.__xss=1\">", "</td><script>window.__xss=1</script>",
           "javascript:window.__xss=1", "\"><svg onload=window.__xss=1>", "expression(window.__xss=1)", "url(javascript:1)",
           "{{7*7}}", "${7*7}", "‮\u0000\u001f​ ", "A" * 5000, "ＦＯＣＵＳ")
VIEW_RE = "**/api/view"


def _load(page, url: str) -> None:
    page.goto(url, wait_until="load")
    page.evaluate("() => navigator.serviceWorker.ready")


def _render(page) -> None:
    page.fill("#at", AT)
    page.fill("#as-of-date", AS_OF)
    page.click("#load")
    page.wait_for_selector("#review-rows tr")


def _wait_for_caches(page, predicate, timeout_s: float = 15.0) -> list:
    """`caches.keys()` が条件を満たすまで Python 側で待つ（wait_for_function に async を渡すと Promise が真になるため）。"""
    deadline = time.monotonic() + timeout_s
    while True:
        keys = page.evaluate("() => caches.keys()")
        if predicate(keys):
            return keys
        assert time.monotonic() < deadline, keys
        time.sleep(0.1)


def _assert_console_clean(messages, sentinels) -> None:
    """browser 自身の network の失敗の記録だけを許す（私たちの code は console に何も出さない）。"""
    for message in messages:
        assert message.startswith("Failed to load resource"), message
        for sentinel in sentinels:
            assert sentinel not in message, sentinel


def _assert_cleared(page, sentinels) -> None:
    assert page.locator("#review-rows tr").count() == 0
    for section in ("#review", "#profile", "#counts"):
        assert page.locator(section).is_hidden(), section
    assert page.text_content("#as-of") == "" and page.text_content("#versions") == ""
    assert not page.locator("#message").is_hidden()
    body = page.text_content("body")
    for sentinel in sentinels:
        assert sentinel not in body, sentinel


def _real_model(port: int) -> dict:
    return body_json(request(port, "POST", "/api/view", GOOD))


def _cache_bodies(page) -> dict:
    return page.evaluate("""async () => {
        const out = {};
        for (const name of await caches.keys()) {
            const cache = await caches.open(name);
            out[name] = {};
            for (const req of await cache.keys()) { out[name][new URL(req.url).pathname] = await (await cache.match(req)).text(); }
        }
        return out;
    }""")


def _assert_storage_clean(page, sentinels, extra_caches=()) -> None:
    state = _storage_state(page)
    assert state["localStorage"] == [] and state["sessionStorage"] == [] and state["indexedDB"] == [] and state["cookies"] == ""
    assert set(state["caches"]) == {P11_SHELL_CACHE_NAME, *extra_caches}
    assert state["caches"][P11_SHELL_CACHE_NAME] == sorted(P11_SHELL_PRECACHE)
    for name, entries in _cache_bodies(page).items():
        for path, text in entries.items():
            assert "/api/" not in path
            if name.startswith("p11-shell-"):
                for sentinel in sentinels:
                    assert sentinel not in text, (name, path, sentinel)


# ================================================ 敵対的な model の文字列（XSS）


def test_a_hostile_model_strings_are_rejected_before_rendering_and_never_execute(browser_app) -> None:
    page, port = browser_app["page"], browser_app["srv"].port
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    _load(page, browser_app["url"])
    base = _real_model(port)
    assert base["entries"], "fixture must yield rows"
    injected = {"model": None}
    page.route(VIEW_RE, lambda route: route.fulfill(status=200, content_type="application/json; charset=utf-8",
                                                    body=json.dumps(injected["model"])))
    injected["model"] = base
    _render(page)                                                                           # 対照: 正しい形は描かれる
    assert page.locator("#review-rows tr").count() == len(base["entries"])
    string_slots = [("at",), ("as_of_date",), ("view_class",), ("schema_version",), ("entries", 0, "source_kind"),
                    ("entries", 0, "p9_status"), ("entries", 0, "attention"), ("entries", 0, "review_due_on"),
                    ("entries", 0, "surface_group"), ("source_schema_versions", "p9")]
    seen = 0
    for payload in HOSTILE:
        for slot in string_slots:
            hostile = copy.deepcopy(base)
            target = hostile
            for key in slot[:-1]:
                target = target[key]
            if slot[-1] not in target and slot[0] != "source_schema_versions":
                continue
            target[slot[-1]] = payload
            injected["model"] = hostile
            page.click("#load")
            page.wait_for_function("() => document.getElementById('message').textContent.includes('RESPONSE_INVALID')")
            _assert_cleared(page, (payload[:12], "__xss", SENTINEL))
            assert page.evaluate("() => window.__xss") is None
            seen += 1
        hostile = copy.deepcopy(base)
        hostile["personal_counts"][payload[:120]] = 1                                       # 鍵にも入れる
        injected["model"] = hostile
        page.click("#load")
        page.wait_for_function("() => document.getElementById('message').textContent.includes('RESPONSE_INVALID')")
        _assert_cleared(page, (payload[:12], "__xss"))
    assert seen >= 100 and dialogs == [] and page.evaluate("() => document.scripts.length") == 1
    assert browser_app["console"] == []
    page.unroute(VIEW_RE)
    _render(page)                                                                           # 明示の再試行で本物に戻る
    assert page.locator("#review-rows tr").count() == len(base["entries"])


# ================================================ 形の崩れた応答 ・失敗の後の古い data


MALFORMED = {
    "array": "[]", "string": "\"ok\"", "null": "null", "number": "1", "empty_object": "{}", "not_json": "<html>oops</html>",
    "truncated_json": "{\"at\": \"2026-01-01T00:00:00+09:00\", \"entries\": [",
}


def test_b_malformed_responses_and_every_failure_kind_clear_the_prior_private_model(browser_app) -> None:
    page, port = browser_app["page"], browser_app["srv"].port
    _load(page, browser_app["url"])
    base = _real_model(port)
    sentinels = tuple(browser_app["sentinels"]) + (SENTINEL,)
    variants = []
    for name, text in MALFORMED.items():
        variants.append((name, dict(status=200, body=text, content_type="application/json")))
    for mutate in ("schema_version", "entries_object", "extra_key", "missing_key", "row_not_object", "ordinal_string",
                   "excluded_string", "too_many_rows", "count_negative", "count_string", "versions_number", "entry_extra_key",
                   "entry_missing_key", "proto_key", "linked_float", "due_bad_date"):
        m = copy.deepcopy(base)
        if mutate == "schema_version": m["schema_version"] = "p11_ui_model:9.9.9"
        if mutate == "entries_object": m["entries"] = {"0": m["entries"][0]}
        if mutate == "extra_key": m["note"] = SENTINEL
        if mutate == "missing_key": del m["p9_counts"]
        if mutate == "row_not_object": m["entries"].append([1, 2, 3])
        if mutate == "ordinal_string": m["entries"][0]["ordinal"] = "0"
        if mutate == "excluded_string": m["entries"][0]["excluded_by_profile"] = "true"
        if mutate == "too_many_rows": m["entries"] = [m["entries"][0]] * 2001
        if mutate == "count_negative": m["personal_counts"]["live_mute_mark_count"] = -1
        if mutate == "count_string": m["p9_counts"][next(iter(m["p9_counts"]))] = SENTINEL
        if mutate == "versions_number": m["source_schema_versions"][next(iter(m["source_schema_versions"]))] = 1
        if mutate == "entry_extra_key": m["entries"][0]["issuer"] = SENTINEL
        if mutate == "entry_missing_key": del m["entries"][0]["attention"]
        if mutate == "proto_key": m["__proto__"] = {"polluted": True}
        if mutate == "linked_float": m["entries"][0]["linked_watch_ordinal"] = 1.5
        if mutate == "due_bad_date": m["entries"][0]["review_due_on"] = "2026-1-1"            # 形だけを見る（暦の意味は server）
        variants.append((mutate, dict(status=200, body=json.dumps(m), content_type="application/json")))
    variants += [("http_500", dict(status=500, body=json.dumps({"code": "INTERNAL_ERROR", "detail": "", "schema_version": "x"}),
                                   content_type="application/json")),
                 ("http_503", dict(status=503, body=json.dumps({"code": "VIEW_UNAVAILABLE", "detail": SENTINEL}),
                                   content_type="application/json")),
                 ("http_500_sentinel_text", dict(status=500, body=SENTINEL + " " + NOTE, content_type="text/plain")),
                 ("http_200_html", dict(status=200, body="<html><script>window.__xss=1</script></html>", content_type="text/html")),
                 ("http_204", dict(status=204, body="")),
                 ("abort", None)]
    for name, fulfil in variants:
        page.unroute(VIEW_RE)
        _render(page)                                                                       # まず本物を描く
        assert page.locator("#review-rows tr").count() == len(base["entries"]), name
        if fulfil is None:
            page.route(VIEW_RE, lambda route: route.abort("failed"))
        else:
            page.route(VIEW_RE, (lambda f: lambda route: route.fulfill(**f))(fulfil))
        page.click("#load")
        page.wait_for_function("() => document.getElementById('review-rows').children.length === 0")
        page.wait_for_function("() => !document.getElementById('message').hidden")
        _assert_cleared(page, sentinels + ("__xss", "polluted"))
        assert page.evaluate("() => window.__xss") is None and page.evaluate("() => ({}).polluted") is None, name
        message = page.text_content("#message")
        assert ("RESPONSE_INVALID" in message or "読み込みを拒否" in message or "届きません" in message), (name, message)
    page.unroute(VIEW_RE)
    _render(page)                                                                           # 不正な時点の入力
    page.fill("#as-of-date", "2026-02-30")
    page.click("#load")
    page.wait_for_function("() => document.getElementById('review-rows').children.length === 0")
    _assert_cleared(page, sentinels)
    _render(page)
    page.fill("#at", "")                                                                    # browser 側の検査で止まる（要求なし）
    calls = _api_calls(browser_app["events"])
    page.click("#load")
    page.wait_for_function("() => document.getElementById('review-rows').children.length === 0")
    _assert_cleared(page, sentinels)
    assert _api_calls(browser_app["events"]) == calls
    _render(page)                                                                           # server の停止
    browser_app["srv"].shutdown()
    page.click("#load")
    page.wait_for_function("() => document.getElementById('review-rows').children.length === 0")
    _assert_cleared(page, sentinels)
    assert "届きません" in page.text_content("#message")
    _assert_console_clean(browser_app["console"], sentinels)
    _assert_storage_clean(page, sentinels)


def test_c_the_request_aborts_after_the_fixed_local_timeout_and_clears_the_model(browser_app) -> None:
    page = browser_app["page"]
    _load(page, browser_app["url"])
    _render(page)
    held = []
    page.route(VIEW_RE, lambda route: held.append(route))                                  # 答えない server
    page.click("#load")
    page.wait_for_function("() => document.getElementById('message').textContent.includes('TIMEOUT')", timeout=20000)
    elapsed = page.evaluate("() => performance.now()")
    assert elapsed >= 10000
    _assert_cleared(page, tuple(browser_app["sentinels"]))
    assert page.get_attribute("#server-status", "data-state") == "down"
    assert len(held) == 1                                                                   # 再試行はしない（人の操作だけ）
    page.click("#load")
    page.wait_for_function("() => performance.now() > 0")
    assert len(held) <= 2
    for route in held:
        route.abort()
    assert browser_app["console"] == []


# ================================================ 時点 ・URL ・history ・reload


def test_d_pit_never_reaches_url_history_or_storage_and_fields_are_empty_after_reload(browser_app) -> None:
    page = browser_app["page"]
    _load(page, browser_app["url"])
    assert page.evaluate("() => document.getElementById('pit-form').method") == "post"
    assert page.evaluate("() => new URL(document.getElementById('pit-form').action).pathname") == "/app/"
    history_before = page.evaluate("() => history.length")
    url_before = page.url
    _render(page)
    page.click("#fill-clock")
    assert page.url == url_before and page.evaluate("() => history.length") == history_before
    assert AT not in page.url and AS_OF not in page.url and "?" not in page.url and "#" not in page.url
    assert page.evaluate("() => history.state") is None
    page.reload(wait_until="load")
    assert page.input_value("#at") == "" and page.input_value("#as-of-date") == ""
    assert page.locator("#review-rows tr").count() == 0
    page.go_back()
    page.go_forward()
    assert page.input_value("#at") == "" and page.input_value("#as-of-date") == ""
    assert page.url == url_before
    _assert_storage_clean(page, tuple(browser_app["sentinels"]) + (AT,))
    assert browser_app["context"].cookies() == []


# ================================================ service worker の更新 ・毒の entry


def test_e_worker_update_removes_only_prior_shell_caches_and_poisoned_entries_are_never_served(browser_app) -> None:
    page = browser_app["page"]
    _load(page, browser_app["url"])
    page.reload(wait_until="load")                                                          # 最初から controller 付き
    page.evaluate("() => navigator.serviceWorker.ready")
    assert page.locator("#update-notice").is_hidden()
    page.evaluate("""async (s) => {
        const old = await caches.open('p11-shell-000000000000');
        await old.put('/app/app.js', new Response('poisoned ' + s, { headers: { 'Content-Type': 'text/javascript' } }));
        const other = await caches.open('unrelated-cache');
        await other.put('/x', new Response('keep ' + s));
        const shell = await caches.open('%s');
        await shell.put('/app/unknown', new Response('poisoned ' + s, { headers: { 'Content-Type': 'text/html' } }));
        await shell.put('/api/view', new Response(JSON.stringify({ entries: [s] }), { headers: { 'Content-Type': 'application/json' } }));
    }""" % P11_SHELL_CACHE_NAME, SENTINEL)
    unknown = page.evaluate("async () => { const r = await fetch('/app/unknown'); return [r.status, await r.text()]; }")
    assert unknown[0] == 404 and SENTINEL not in unknown[1] and json.loads(unknown[1])["code"] == "NOT_FOUND"
    view = page.evaluate("async () => { const r = await fetch('/api/view'); return [r.status, await r.text()]; }")
    assert view[0] == 405 and SENTINEL not in view[1]                                       # /api/ は SW を経ない
    shell_js = page.evaluate("async () => (await fetch('/app/app.js')).text()")
    assert shell_js == (REPO_ROOT / PHASE11_STATIC_DIR / "app.js").read_bytes().decode("utf-8")
    # 新しい版の sw.js（cache の名前が変わる）を server が配るようにして update → 新しい worker が install ・activate
    assets = browser_app["srv"]._server.context.static_assets                              # test だけ: 配る byte を入れ替える
    assets["/app/sw.js"] = assets["/app/sw.js"].replace(P11_SHELL_CACHE_NAME.encode(), b"p11-shell-aaaaaaaaaaaa")
    page.evaluate("async () => { const reg = await navigator.serviceWorker.getRegistration('/app/'); await reg.update(); }")
    _wait_for_caches(page, lambda keys: "p11-shell-aaaaaaaaaaaa" in keys and "p11-shell-000000000000" not in keys
                     and P11_SHELL_CACHE_NAME not in keys)
    page.wait_for_function("() => !document.getElementById('update-notice').hidden")      # 一般の「新しい版」の表示
    state = _storage_state(page)
    assert set(state["caches"]) == {"p11-shell-aaaaaaaaaaaa", "unrelated-cache"}           # 他の namespace には触れない
    assert state["caches"]["p11-shell-aaaaaaaaaaaa"] == sorted(P11_SHELL_PRECACHE)
    assert state["caches"]["unrelated-cache"] == ["/x"]
    bodies = _cache_bodies(page)
    assert all(SENTINEL not in text for text in bodies["p11-shell-aaaaaaaaaaaa"].values())
    assert bodies["unrelated-cache"]["/x"] == "keep " + SENTINEL
    assert page.evaluate("() => navigator.serviceWorker.controller.scriptURL").endswith("/app/sw.js")
    assert page.locator("#review-rows tr").count() == 0 and page.input_value("#at") == ""     # 更新で private な data は出ない
    _assert_console_clean(browser_app["console"], (SENTINEL,))                                # 404 ／ 405 の probe の記録だけ


# ================================================ 外部の network ゼロ ・console 空 ・cookie 空 ・保存の証明


def test_f_zero_external_requests_no_console_no_cookies_and_storage_clean_at_every_stage(browser_app) -> None:
    page, port = browser_app["page"], browser_app["srv"].port
    requests, set_cookies = [], []
    page.on("request", lambda r: requests.append(r.url))
    page.on("response", lambda r: set_cookies.append(r.headers.get("set-cookie")))
    sentinels = tuple(browser_app["sentinels"]) + (AT,)
    _load(page, browser_app["url"])
    _assert_storage_clean(page, sentinels)                                                  # 1. 最初の load
    _render(page)
    _assert_storage_clean(page, sentinels)                                                  # 2. 描画
    page.click("#load")
    page.wait_for_selector("#review-rows tr")
    _assert_storage_clean(page, sentinels)                                                  # 3. 繰り返し
    page.route(VIEW_RE, lambda route: route.fulfill(status=500, body="{}", content_type="application/json"))
    page.click("#load")
    page.wait_for_function("() => document.getElementById('review-rows').children.length === 0")
    page.unroute(VIEW_RE)
    _assert_storage_clean(page, sentinels)                                                  # 4. API の失敗
    browser_app["context"].set_offline(True)
    page.reload(wait_until="load")
    assert page.locator("#offline").is_visible() and page.locator("#review-rows tr").count() == 0
    _assert_storage_clean(page, sentinels)                                                  # 5. offline の reload
    browser_app["context"].set_offline(False)
    page.evaluate("""async () => {
        const reg = await navigator.serviceWorker.getRegistration('/app/');
        await reg.unregister();
        await navigator.serviceWorker.register('/app/sw.js', { scope: '/app/' });
        await navigator.serviceWorker.ready;
    }""")
    _assert_storage_clean(page, sentinels)                                                  # 6. worker の更新
    assert requests and all(r.startswith(f"http://127.0.0.1:{port}/") for r in requests), requests
    assert all(sc is None for sc in set_cookies) and browser_app["context"].cookies() == []
    assert page.evaluate("() => document.cookie") == ""
    _assert_console_clean(browser_app["console"], sentinels)
    hosts = {r.split("/")[2] for r in requests}
    assert hosts == {f"127.0.0.1:{port}"}


# ================================================ accessibility の smoke ・keyboard


def test_g_accessibility_smoke_and_keyboard_submit(browser_app) -> None:
    page = browser_app["page"]
    _load(page, browser_app["url"])
    labels = page.evaluate("""() => Array.from(document.querySelectorAll('label')).map((l) => [l.htmlFor,
        !!document.getElementById(l.htmlFor)])""")
    assert labels and all(ok for _id, ok in labels) and {i for i, _ in labels} == {"at", "as-of-date"}
    assert page.get_attribute("#status-area", "aria-live") == "polite"
    assert page.get_attribute("#server-status", "role") == "status"
    assert page.evaluate("() => document.documentElement.lang") == "ja"
    assert page.evaluate("() => Array.from(document.querySelectorAll('th')).every((th) => th.scope === 'col')")
    page.fill("#at", AT)
    page.fill("#as-of-date", AS_OF)
    page.focus("#as-of-date")
    page.keyboard.press("Enter")                                                            # keyboard だけで送れる
    page.wait_for_selector("#review-rows tr")
    rows = page.locator("#review-rows tr")
    marks = {rows.nth(i).locator("td").nth(6).text_content() for i in range(rows.count())}
    assert marks <= {"FOCUS", "NORMAL", "MUTE"} and "MUTE" in marks                        # 印は文字で（色だけでない）
    excluded = page.locator("#review-rows tr[data-excluded='true']")
    assert excluded.count() >= 1 and all(excluded.nth(i).locator("td").nth(7).text_content() == "除外"
                                         for i in range(excluded.count()))
    assert "offline" in page.text_content("#offline") and page.locator("#offline").is_hidden()
    assert browser_app["console"] == []
