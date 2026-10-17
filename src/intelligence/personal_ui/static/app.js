'use strict';
// P11-A3 — private local PWA shell. Renders the read-only P11-A1 UI model served by the loopback server.
// The model lives only in this closure (never in storage, URLs or the console). Nothing is written anywhere.
(function () {
  const VIEW_ROUTE = '/api/view';
  const AT_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?[+-]\d{2}:\d{2}$/;
  const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  const SAFE_CODE_RE = /^[A-Z0-9_:]{1,120}$/;
  const PROFILE_FIELDS = [
    ['active_profile_present', 'ACTIVE な profile'],
    ['review_lookahead_days', '見直しの窓（日）'],
    ['excluded_by_profile_count', '除外された行（件数）']
  ];
  const ENTRY_COLUMNS = ['ordinal', 'source_kind', 'p9_status', 'p9_provenance_kind', 'review_due_on', 'due_class',
    'attention', 'excluded_by_profile', 'surface_group', 'linked_watch_ordinal'];

  let model = null; // in-memory only

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
    for (const id of ['profile', 'counts', 'review']) { el(id).hidden = true; }
  }

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
    model = data;
    renderDefinitions(el('profile-list'), PROFILE_FIELDS.map(([key, label]) => [label,
      key === 'excluded_by_profile_count' ? data.personal_counts[key] : data[key]]));
    renderDefinitions(el('personal-counts'), Object.entries(data.personal_counts));
    renderDefinitions(el('p9-counts'), Object.entries(data.p9_counts));
    const rows = el('review-rows');
    clearChildren(rows);
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

  async function load(event) {
    event.preventDefault();
    hideMessage();
    const at = el('at').value.trim();
    const asOfDate = el('as-of-date').value.trim();
    if (!AT_RE.test(at) || !DATE_RE.test(asOfDate)) {
      clearModel();
      showMessage('at と as_of_date を明示に入力してください（at は offset 付きの瞬間、as_of_date は YYYY-MM-DD）。');
      return;
    }
    let response;
    try {
      response = await fetch(VIEW_ROUTE, {
        method: 'POST', mode: 'same-origin', credentials: 'omit', cache: 'no-store', redirect: 'error',
        referrerPolicy: 'no-referrer', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ at: at, as_of_date: asOfDate })
      });
    } catch (error) {
      clearModel();
      setServerState('down', 'local server unavailable');
      setOffline(!navigator.onLine);
      showMessage('local server に届きません。private な data は表示しません。');
      return;
    }
    let payload = null;
    try { payload = await response.json(); } catch (error) { payload = null; }
    if (!response.ok || !payload || typeof payload !== 'object') {
      clearModel();
      setServerState('ok', 'reachable');
      showMessage('読み込みを拒否: ' + safeCode(payload) + '（status ' + response.status + '）');
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
    navigator.serviceWorker.register('/app/sw.js', { scope: '/app/' }).catch(function () {
      setServerState('unknown', 'shell worker not registered');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    el('pit-form').addEventListener('submit', load);
    el('fill-clock').addEventListener('click', fillFromDeviceClock);
    window.addEventListener('offline', function () { setOffline(true); });
    window.addEventListener('online', function () { setOffline(false); setServerState('unknown', '未接続'); });
    setOffline(!navigator.onLine);
    registerShell();
  });
})();
