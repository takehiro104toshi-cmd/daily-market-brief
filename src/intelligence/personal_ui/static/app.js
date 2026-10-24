'use strict';
// P11-A3 ／ A4 — private local PWA shell. Renders the read-only P11-A1 UI model served by the loopback server.
// The model lives only in this closure (never in storage, URLs or the console). Nothing is written anywhere.
// A4: the response is validated against the presentation schema before anything is rendered; any failure clears
// the previous private model from the DOM and from memory; the request aborts after a fixed local timeout.
(function () {
  const VIEW_ROUTE = '/api/view';
  const UI_MODEL_SCHEMA_VERSION = 'p11_ui_model:0.1.0';
  const FETCH_TIMEOUT_MS = 10000;
  const MAX_ROWS = 2000;
  const MAX_KEYS = 64;
  const AT_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?[+-]\d{2}:\d{2}$/;
  const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  const SAFE_CODE_RE = /^[A-Z0-9_:]{1,120}$/;
  const CODE_RE = /^[A-Z0-9_]{0,80}$/; // governed codes; empty is a legitimate 'none'
  const KEY_RE = /^[A-Za-z0-9_.]{1,80}$/; // count keys may carry a dotted vocabulary suffix
  const VERSION_RE = /^[a-z0-9_.:+-]{1,80}$/;
  const TOP_KEYS = ['at', 'as_of_date', 'active_profile_present', 'review_lookahead_days', 'personal_counts',
    'p9_counts', 'unmatched_live_mark_count', 'entries', 'source_schema_versions', 'schema_version', 'view_class'];
  const ENTRY_COLUMNS = ['ordinal', 'source_kind', 'p9_status', 'p9_provenance_kind', 'review_due_on', 'due_class',
    'attention', 'excluded_by_profile', 'surface_group', 'linked_watch_ordinal'];
  const PROFILE_FIELDS = [
    ['active_profile_present', 'ACTIVE な profile'],
    ['review_lookahead_days', '見直しの窓（日）'],
    ['excluded_by_profile_count', '除外された行（件数）']
  ];

  let model = null; // in-memory only; replaced on success, nulled on any failure
  let inFlight = false;

  const el = (id) => document.getElementById(id);

  function setText(node, text) { node.textContent = text; }

  function clearChildren(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }

  function setServerState(state, label) {
    const status = el('server-status');
    status.dataset.state = state;
    setText(status, 'server: ' + label);
  }

  function showMessage(text) {
    const message = el('message');
    setText(message, text);
    message.hidden = false;
  }

  function hideMessage() { el('message').hidden = true; }

  function setOffline(isOffline) {
    el('offline').hidden = !isOffline;
    if (isOffline) { setServerState('offline', 'offline — private data is unavailable'); }
  }

  function clearModel() {
    model = null;
    for (const id of ['profile-list', 'personal-counts', 'p9-counts', 'review-rows']) { clearChildren(el(id)); }
    setText(el('as-of'), '');
    setText(el('versions'), '');
    for (const id of ['profile', 'counts', 'review']) { el(id).hidden = true; }
  }

  // ---- presentation-schema validation (shape and primitive types only; no investment semantics)
  function isPlainObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value) && Object.getPrototypeOf(value) === Object.prototype;
  }

  function isCount(value) { return Number.isInteger(value) && value >= 0 && value <= 1000000000; }

  function isCode(value) { return typeof value === 'string' && CODE_RE.test(value); }

  function hasExactKeys(object, keys) {
    const own = Object.keys(object);
    return own.length === keys.length && keys.every(function (key) { return Object.prototype.hasOwnProperty.call(object, key); });
  }

  function isCountMap(value) {
    if (!isPlainObject(value)) { return false; }
    const keys = Object.keys(value);
    return keys.length <= MAX_KEYS && keys.every(function (key) { return KEY_RE.test(key) && isCount(value[key]); });
  }

  function isVersionMap(value) {
    if (!isPlainObject(value)) { return false; }
    const keys = Object.keys(value);
    return keys.length <= MAX_KEYS && keys.every(function (key) {
      return KEY_RE.test(key) && typeof value[key] === 'string' && VERSION_RE.test(value[key]);
    });
  }

  function isEntry(entry) {
    return isPlainObject(entry) && hasExactKeys(entry, ENTRY_COLUMNS)
      && isCount(entry.ordinal)
      && isCode(entry.source_kind) && isCode(entry.p9_status) && isCode(entry.p9_provenance_kind)
      && (entry.review_due_on === null || (typeof entry.review_due_on === 'string' && DATE_RE.test(entry.review_due_on)))
      && isCode(entry.due_class) && isCode(entry.attention) && isCode(entry.surface_group)
      && typeof entry.excluded_by_profile === 'boolean'
      && (entry.linked_watch_ordinal === null || isCount(entry.linked_watch_ordinal));
  }

  function isUiModel(data) {
    return isPlainObject(data) && hasExactKeys(data, TOP_KEYS)
      && data.schema_version === UI_MODEL_SCHEMA_VERSION
      && typeof data.at === 'string' && AT_RE.test(data.at)
      && typeof data.as_of_date === 'string' && DATE_RE.test(data.as_of_date)
      && typeof data.active_profile_present === 'boolean'
      && isCount(data.review_lookahead_days) && isCount(data.unmatched_live_mark_count)
      && isCountMap(data.personal_counts) && isCountMap(data.p9_counts) && isVersionMap(data.source_schema_versions)
      && isCode(data.view_class)
      && Array.isArray(data.entries) && data.entries.length <= MAX_ROWS && data.entries.every(isEntry);
  }

  // ---- rendering (textContent / createElement only)
  function formatValue(value) {
    if (value === null || value === undefined) { return '—'; }
    if (value === true) { return 'yes'; }
    if (value === false) { return 'no'; }
    return String(value);
  }

  function renderDefinitions(node, pairs) {
    clearChildren(node);
    for (const [key, value] of pairs) {
      const dt = document.createElement('dt');
      setText(dt, key);
      const dd = document.createElement('dd');
      setText(dd, formatValue(value));
      node.append(dt, dd);
    }
  }

  function renderModel(data) {
    clearModel();
    model = data;
    renderDefinitions(el('profile-list'), PROFILE_FIELDS.map(([key, label]) => [label,
      key === 'excluded_by_profile_count' ? data.personal_counts[key] : data[key]]));
    renderDefinitions(el('personal-counts'), Object.entries(data.personal_counts));
    renderDefinitions(el('p9-counts'), Object.entries(data.p9_counts));
    const rows = el('review-rows');
    for (const entry of data.entries) { // response order is preserved exactly; no re-sorting
      const tr = document.createElement('tr');
      tr.dataset.attention = entry.attention;
      tr.dataset.excluded = entry.excluded_by_profile ? 'true' : 'false';
      for (const column of ENTRY_COLUMNS) {
        const td = document.createElement('td');
        const value = entry[column];
        setText(td, column === 'excluded_by_profile' ? (value ? '除外' : '') : formatValue(value));
        tr.append(td);
      }
      rows.append(tr);
    }
    setText(el('as-of'), data.at + ' / ' + data.as_of_date);
    setText(el('versions'), 'schema ' + data.schema_version + ' · ' + Object.entries(data.source_schema_versions)
      .map(([key, value]) => key + ' ' + value).join(' · '));
    for (const id of ['profile', 'counts', 'review']) { el(id).hidden = false; }
  }

  function safeCode(payload) {
    const code = payload && typeof payload.code === 'string' && SAFE_CODE_RE.test(payload.code) ? payload.code : 'UNKNOWN';
    const detail = payload && typeof payload.detail === 'string' && SAFE_CODE_RE.test(payload.detail) ? payload.detail : '';
    return detail ? code + ':' + detail : code;
  }

  function fail(state, label, text) {
    clearModel();
    setServerState(state, label);
    showMessage(text);
  }

  async function load(event) {
    event.preventDefault();
    if (inFlight) { return; } // one explicit request at a time; no retry loop
    hideMessage();
    const at = el('at').value.trim();
    const asOfDate = el('as-of-date').value.trim();
    if (!AT_RE.test(at) || !DATE_RE.test(asOfDate)) {
      clearModel();
      showMessage('at と as_of_date を明示に入力してください（at は offset 付きの瞬間、as_of_date は YYYY-MM-DD）。');
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(function () { controller.abort(); }, FETCH_TIMEOUT_MS);
    inFlight = true;
    let response;
    try {
      response = await fetch(VIEW_ROUTE, {
        method: 'POST', mode: 'same-origin', credentials: 'omit', cache: 'no-store', redirect: 'error',
        referrerPolicy: 'no-referrer', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ at: at, as_of_date: asOfDate }), signal: controller.signal
      });
    } catch (error) {
      clearTimeout(timer);
      inFlight = false;
      if (controller.signal.aborted) {
        fail('down', 'no answer within the local timeout', '読み込みを中止: TIMEOUT（local server が時間内に答えません。private な data は表示しません）。');
      } else {
        fail('down', 'local server unavailable', 'local server に届きません。private な data は表示しません。');
        setOffline(!navigator.onLine);
      }
      return;
    }
    let payload = null;
    try { payload = await response.json(); } catch (error) { payload = null; }
    clearTimeout(timer);
    inFlight = false;
    if (!response.ok) {
      fail('ok', 'reachable', '読み込みを拒否: ' + safeCode(isPlainObject(payload) ? payload : null) + '（status ' + response.status + '）');
      return;
    }
    if (!isUiModel(payload)) { // malformed or unexpected response: nothing of it is rendered or kept
      fail('ok', 'reachable', '読み込みを中止: RESPONSE_INVALID（応答の形が UI model の schema と一致しません）。');
      return;
    }
    setOffline(false);
    setServerState('ok', 'reachable');
    renderModel(payload);
  }

  function pad(n) { return String(n).padStart(2, '0'); }

  function fillFromDeviceClock() {
    const now = new Date();
    const offsetMinutes = -now.getTimezoneOffset();
    const sign = offsetMinutes >= 0 ? '+' : '-';
    const abs = Math.abs(offsetMinutes);
    const date = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate());
    el('at').value = date + 'T' + pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds())
      + sign + pad(Math.floor(abs / 60)) + ':' + pad(abs % 60);
    el('as-of-date').value = date;
    showMessage('この端末の時計で欄を埋めました（送信はしていません。「読み込む」で明示に送ります）。');
  }

  function registerShell() {
    if (!('serviceWorker' in navigator) || window.location.hostname !== '127.0.0.1') { return; }
    const hadController = navigator.serviceWorker.controller !== null;
    navigator.serviceWorker.addEventListener('controllerchange', function () {
      if (hadController) { el('update-notice').hidden = false; } // a newer shell took over; no reload is forced
    });
    navigator.serviceWorker.register('/app/sw.js', { scope: '/app/' }).catch(function () {
      setServerState('unknown', 'shell worker not registered');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    el('pit-form').addEventListener('submit', load);
    el('fill-clock').addEventListener('click', fillFromDeviceClock);
    window.addEventListener('offline', function () { clearModel(); setOffline(true); });
    window.addEventListener('online', function () { setOffline(false); setServerState('unknown', '未接続'); });
    setOffline(!navigator.onLine);
    registerShell();
  });
})();
