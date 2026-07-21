/**
 * Cloudflare Worker: Rashinban Private Insight Vault — Private Intake API
 *
 * 既存の trigger-report-worker.js とは完全に分離した新規Workerモジュール。
 * GitHub Pages（静的サイト）はデータ保存ができないため、private記事本文の
 * 唯一の永続保存先としてこのWorker + KV（非公開）を使う。
 *
 * ★保存アーキテクチャ（重要）:
 *   daily-market-brief / article-intelligence-data-tank は両方ともPublicリポジトリの
 *   ため、リポジトリへコミットされたものはすべて公開になる。したがって本文の保存先は
 *   Cloudflare KV（このWorkerにバインド）のみとし、GitHub側には一切書き込まない。
 *   分析はData Tank側のGitHub Actions（scripts/run_private_insight_analysis.py）が
 *   /queue から取得→メモリ内で分析→ /analysis/{id} へ結果を返す。
 *
 * 必要なバインディング / Secret（wranglerまたはダッシュボードで設定）:
 *   - KVネームスペース: INSIGHT_KV                              … 必須
 *   - PASSPHRASE_SHA256 … 人間用パスフレーズのSHA-256（hex小文字）。※Secret必須
 *   - INSIGHT_API_TOKEN … 分析パイプライン（GitHub Actions）用の機械トークン。※Secret必須
 *   - ENCRYPTION_KEY_B64 … 本文AES-GCM暗号化用の32byte鍵（base64）。省略時は平文でKVへ
 *   - ALLOWED_ORIGIN    … 例: https://takehiro104toshi-cmd.github.io
 *   - MAX_BODY_CHARS    … 既定 30000
 *   - RATE_LIMIT_PER_HOUR … 既定 20
 *
 * API（base: /api/private-insight）:
 *   POST /intake            … 記事本文の受け付け（人間用認証: X-Insight-Key）
 *   GET  /status/{id}       … 保存/分析状態（人間用認証。本文は返さない）
 *   GET  /list              … メタデータ一覧（人間用認証。本文は返さない）
 *   POST /delete/{id}       … 削除 {permanent: bool}（人間用認証）
 *   POST /memo/{id}         … メモ/タグ編集（人間用認証）
 *   POST /reanalyze/{id}    … 再分析キュー投入（人間用認証）
 *   GET  /queue             … 未分析記事の取得（機械用: Bearer token。本文を含む唯一のAPI）
 *   POST /analysis/{id}     … 分析結果・派生情報の保存（機械用: Bearer token）
 *   GET  /derived           … 公開可能な派生情報一覧（機械用: Bearer token）
 *   GET  /admin             … 認証済み管理画面（このWorkerが直接配信。Pagesには置かない）
 *
 * セキュリティ:
 *   - パスフレーズ・トークンはSecretのみ。HTMLへ埋め込まない
 *   - 人間用APIのレスポンスへ本文を一切含めない（/queueは機械専用）
 *   - エラーログ・レスポンスへ本文を出力しない
 *   - rate limit / サイズ上限 / Content-Type検証 / 重複送信保護
 */

const BASE = "/api/private-insight";
const DEFAULT_MAX_BODY_CHARS = 30000;
const MAX_REQUEST_BYTES = 150000;
const DEFAULT_RATE_LIMIT = 20;

function corsHeaders(origin, allowedOrigin) {
  const h = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Insight-Key, Authorization",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
  if (origin && origin === allowedOrigin) h["Access-Control-Allow-Origin"] = allowedOrigin;
  return h;
}

function json(body, status, extra) {
  return new Response(JSON.stringify(body), {
    status,
    headers: Object.assign(
      { "Content-Type": "application/json", "Cache-Control": "no-store" }, extra || {}),
  });
}

async function sha256hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// タイミング攻撃対策の定数時間比較（長さ一致前提の単純比較で十分な用途）
function safeEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function humanAuth(request, env) {
  const key = request.headers.get("X-Insight-Key") || "";
  if (!env.PASSPHRASE_SHA256 || !key) return false;
  return safeEqual(await sha256hex(key), env.PASSPHRASE_SHA256.toLowerCase());
}

function machineAuth(request, env) {
  const auth = request.headers.get("Authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  return !!env.INSIGHT_API_TOKEN && safeEqual(token, env.INSIGHT_API_TOKEN);
}

// ---------- AES-GCM 暗号化（ENCRYPTION_KEY_B64 設定時のみ） ----------

async function importKey(env) {
  if (!env.ENCRYPTION_KEY_B64) return null;
  const raw = Uint8Array.from(atob(env.ENCRYPTION_KEY_B64), (c) => c.charCodeAt(0));
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function encryptBody(env, text) {
  const key = await importKey(env);
  if (!key) return { data: text, encrypted: false };
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv },
    key, new TextEncoder().encode(text));
  const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
  return { data: `enc:v1:${b64(iv)}:${b64(ct)}`, encrypted: true };
}

async function decryptBody(env, stored) {
  if (!stored || !stored.startsWith("enc:v1:")) return stored || "";
  const key = await importKey(env);
  if (!key) return "";
  const [, , ivB64, ctB64] = stored.split(":");
  const un64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: un64(ivB64) }, key, un64(ctB64));
  return new TextDecoder().decode(pt);
}

// ---------- rate limit（KVカウンタ・時間単位） ----------

async function rateLimited(env, bucketKey) {
  const hour = new Date().toISOString().slice(0, 13);
  const key = `rl:${bucketKey}:${hour}`;
  const current = parseInt((await env.INSIGHT_KV.get(key)) || "0", 10);
  const limit = parseInt(env.RATE_LIMIT_PER_HOUR || DEFAULT_RATE_LIMIT, 10);
  if (current >= limit) return true;
  await env.INSIGHT_KV.put(key, String(current + 1), { expirationTtl: 7200 });
  return false;
}

// ---------- handlers ----------

async function handleIntake(request, env) {
  const ct = request.headers.get("Content-Type") || "";
  if (!ct.includes("application/json")) return json({ ok: false, error: "content_type" }, 415);
  const raw = await request.text();
  if (raw.length > (parseInt(env.MAX_REQUEST_BYTES || MAX_REQUEST_BYTES, 10))) {
    return json({ ok: false, error: "request_too_large" }, 413);
  }
  let p;
  try { p = JSON.parse(raw); } catch { return json({ ok: false, error: "bad_json" }, 400); }

  const body = (p.body || "").trim();
  const maxChars = parseInt(env.MAX_BODY_CHARS || DEFAULT_MAX_BODY_CHARS, 10);
  if (!body) return json({ ok: false, error: "empty_body" }, 400);
  if (body.length > maxChars) return json({ ok: false, error: "body_too_long", max: maxChars }, 413);

  if (await rateLimited(env, "intake")) return json({ ok: false, error: "rate_limited" }, 429);

  const normalized = body.replace(/[\s　]+/g, "");
  const bodyHash = await sha256hex(normalized);
  const now = new Date();
  const nowUtc = now.toISOString();
  const nowJst = new Date(now.getTime() + 9 * 3600 * 1000).toISOString().replace("Z", "+09:00");
  const requestId = "req_" + crypto.randomUUID().replace(/-/g, "").slice(0, 12);

  // 重複送信保護: 同一本文は新規保存せず履歴だけ追加
  const dupId = await env.INSIGHT_KV.get(`hash:${bodyHash}`);
  if (dupId) {
    const metaRaw = await env.INSIGHT_KV.get(`meta:${dupId}`);
    if (metaRaw) {
      const meta = JSON.parse(metaRaw);
      meta.submitted_history = (meta.submitted_history || []).concat([nowUtc]);
      if (p.user_note) meta.user_note = ((meta.user_note || "") + "\n" + p.user_note).trim();
      meta.last_updated_at = nowUtc;
      await env.INSIGHT_KV.put(`meta:${dupId}`, JSON.stringify(meta));
      return json({ ok: true, status: "duplicate", private_article_id: dupId, request_id: requestId });
    }
  }

  const id = "pai_" + bodyHash.slice(0, 20);
  const enc = await encryptBody(env, body);
  const meta = {
    private_article_id: id,
    request_id: requestId,
    source_name: (p.source_name || "").slice(0, 100),
    source_url: (p.source_url || "").slice(0, 500),
    title: (p.title || "").slice(0, 200) || `無題のprivate記事（${nowJst.slice(5, 16)}保存）`,
    intake_method: "manual_paste",
    rights_classification: p.rights_classification || "user_private_paid_article",
    visibility: "private",
    body_hash: bodyHash,
    character_count: body.length,
    body_available: true,
    raw_body_encrypted: enc.encrypted,
    submitted_at_utc: nowUtc,
    submitted_at_jst: nowJst,
    submitted_history: [nowUtc],
    article_published_at: (p.article_published_at || "").slice(0, 40),
    client_timezone: (p.client_timezone || "").slice(0, 40),
    source_page: (p.source_page || "").slice(0, 200),
    user_note: (p.user_note || "").slice(0, 2000),
    reason_for_interest: (p.reason_for_interest || "").slice(0, 1000),
    user_tags: Array.isArray(p.user_tags) ? p.user_tags.slice(0, 10) : [],
    status: "queued",
    retry_count: 0,
    last_updated_at: nowUtc,
    delete_type: "",
  };
  await env.INSIGHT_KV.put(`raw:${id}`, enc.data);
  await env.INSIGHT_KV.put(`meta:${id}`, JSON.stringify(meta));
  await env.INSIGHT_KV.put(`hash:${bodyHash}`, id);
  // レスポンスへ本文は返さない
  return json({ ok: true, status: "stored", private_article_id: id, request_id: requestId,
                submitted_at_jst: nowJst, character_count: body.length });
}

function stripPrivateFields(meta) {
  const { user_note, ...rest } = meta;  // 一覧APIでもuser_noteは省く（memo APIで個別取得）
  return rest;
}

async function listMetas(env, includeDeleted) {
  const out = [];
  let cursor = undefined;
  do {
    const page = await env.INSIGHT_KV.list({ prefix: "meta:", cursor });
    for (const k of page.keys) {
      const raw = await env.INSIGHT_KV.get(k.name);
      if (!raw) continue;
      const meta = JSON.parse(raw);
      if (!includeDeleted && meta.delete_type) continue;
      out.push(meta);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  out.sort((a, b) => (b.submitted_at_utc || "").localeCompare(a.submitted_at_utc || ""));
  return out;
}

async function handleQueue(env, limit) {
  const metas = (await listMetas(env, false))
    .filter((m) => ["queued", "stored", "failed_analysis"].includes(m.status))
    .slice(0, limit);
  const items = [];
  for (const m of metas) {
    const stored = await env.INSIGHT_KV.get(`raw:${m.private_article_id}`);
    const body = await decryptBody(env, stored);
    if (!body) continue;
    items.push(Object.assign({}, m, { body }));
    m.status = "analyzing";
    m.last_updated_at = new Date().toISOString();
    await env.INSIGHT_KV.put(`meta:${m.private_article_id}`, JSON.stringify(m));
  }
  return json({ ok: true, items });
}

async function handleAnalysisPost(request, env, id) {
  let p;
  try { p = await request.json(); } catch { return json({ ok: false, error: "bad_json" }, 400); }
  const metaRaw = await env.INSIGHT_KV.get(`meta:${id}`);
  if (!metaRaw) return json({ ok: false, error: "not_found" }, 404);
  const meta = JSON.parse(metaRaw);
  const now = new Date().toISOString();
  if (p.analysis) await env.INSIGHT_KV.put(`analysis:${id}`, JSON.stringify(p.analysis));
  if (p.derived) await env.INSIGHT_KV.put(`derived:${id}`, JSON.stringify(p.derived));
  meta.status = p.status || "completed";
  meta.analyzed_at = now;
  meta.last_updated_at = now;
  if (p.analysis) {
    meta.model_provider = p.analysis.model_provider || "";
    meta.model_name = p.analysis.model_name || "";
    meta.analysis_version = p.analysis.analysis_version || "v1";
  }
  await env.INSIGHT_KV.put(`meta:${id}`, JSON.stringify(meta));
  return json({ ok: true, status: meta.status });
}

async function handleDerived(env) {
  const metas = await listMetas(env, false);
  const items = [];
  for (const m of metas) {
    const d = await env.INSIGHT_KV.get(`derived:${m.private_article_id}`);
    if (d) items.push(JSON.parse(d));
  }
  return json({ ok: true, items, count: items.length });
}

async function handleDelete(request, env, id) {
  let p = {};
  try { p = await request.json(); } catch { /* 空bodyはsoft delete扱い */ }
  const metaRaw = await env.INSIGHT_KV.get(`meta:${id}`);
  if (!metaRaw) return json({ ok: false, error: "not_found" }, 404);
  const meta = JSON.parse(metaRaw);
  const now = new Date().toISOString();
  const permanent = p.permanent === true && p.confirm === true;  // 完全削除は確認必須
  meta.deleted_at = now;
  meta.delete_type = permanent ? "permanent" : "soft";
  meta.deleted_by = "user";
  meta.delete_reason = (p.reason || "").slice(0, 200);
  if (permanent) {
    await env.INSIGHT_KV.delete(`raw:${id}`);
    await env.INSIGHT_KV.delete(`analysis:${id}`);
    await env.INSIGHT_KV.delete(`derived:${id}`);
    if (meta.body_hash) await env.INSIGHT_KV.delete(`hash:${meta.body_hash}`);
    meta.body_available = false;
  } else {
    // soft deleteでも派生情報はレポートから消す
    await env.INSIGHT_KV.delete(`derived:${id}`);
  }
  await env.INSIGHT_KV.put(`meta:${id}`, JSON.stringify(meta));
  return json({ ok: true, delete_type: meta.delete_type });
}

async function handleMemo(request, env, id) {
  let p;
  try { p = await request.json(); } catch { return json({ ok: false, error: "bad_json" }, 400); }
  const metaRaw = await env.INSIGHT_KV.get(`meta:${id}`);
  if (!metaRaw) return json({ ok: false, error: "not_found" }, 404);
  const meta = JSON.parse(metaRaw);
  if (typeof p.user_note === "string") meta.user_note = p.user_note.slice(0, 2000);
  if (Array.isArray(p.user_tags)) meta.user_tags = p.user_tags.slice(0, 10);
  meta.last_updated_at = new Date().toISOString();
  await env.INSIGHT_KV.put(`meta:${id}`, JSON.stringify(meta));
  return json({ ok: true });
}

async function handleReanalyze(env, id) {
  const metaRaw = await env.INSIGHT_KV.get(`meta:${id}`);
  if (!metaRaw) return json({ ok: false, error: "not_found" }, 404);
  const meta = JSON.parse(metaRaw);
  if (!meta.body_available) return json({ ok: false, error: "body_missing" }, 409);
  meta.status = "queued";
  meta.retry_count = (meta.retry_count || 0) + 1;
  meta.last_updated_at = new Date().toISOString();
  await env.INSIGHT_KV.put(`meta:${id}`, JSON.stringify(meta));
  return json({ ok: true, status: "queued" });
}

// ---------- 管理画面（Worker配信・認証済みのみ操作可能） ----------

const ADMIN_HTML = `<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Private Insight 管理</title>
<style>body{font-family:sans-serif;max-width:860px;margin:0 auto;padding:12px;background:#111;color:#eee}
input,button,textarea{font-size:16px;padding:8px;border-radius:8px;border:1px solid #555;background:#222;color:#eee}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{border-bottom:1px solid #333;padding:6px;text-align:left}
button{cursor:pointer;margin:2px}.danger{background:#7f1d1d}.ok{color:#4ade80}.bad{color:#f87171}</style></head>
<body><h2>🧠 Private Insight 管理画面</h2>
<p>パスフレーズ: <input type="password" id="pk"> <button onclick="load()">一覧を読み込む</button>
<span id="msg"></span></p><div id="list"></div>
<script>
const B=location.origin+"${BASE}";
function hdr(){return {"X-Insight-Key":document.getElementById("pk").value,"Content-Type":"application/json"}}
async function load(){
  const r=await fetch(B+"/list",{headers:hdr()});const d=await r.json().catch(()=>({}));
  const m=document.getElementById("msg");
  if(!r.ok){m.textContent="認証失敗または取得エラー";m.className="bad";return}
  m.textContent="OK（"+d.items.length+"件）";m.className="ok";
  let h="<table><tr><th>タイトル</th><th>出典</th><th>送信</th><th>状態</th><th>次回検証</th><th>操作</th></tr>";
  for(const it of d.items){
    h+="<tr><td>"+esc(it.title)+"</td><td>"+esc(it.source_name||"")+"</td><td>"+(it.submitted_at_jst||"").slice(5,16)+
       "</td><td>"+esc(it.status)+"</td><td>"+esc(it.next_review_date||"-")+
       "</td><td><button onclick=\\"act('reanalyze','"+it.private_article_id+"')\\">再分析</button>"+
       "<button onclick=\\"del('"+it.private_article_id+"',false)\\">削除</button>"+
       "<button class=danger onclick=\\"del('"+it.private_article_id+"',true)\\">完全削除</button></td></tr>";
  }
  document.getElementById("list").innerHTML=h+"</table>";
}
function esc(s){return String(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]))}
async function act(a,id){await fetch(B+"/"+a+"/"+id,{method:"POST",headers:hdr(),body:"{}"});load()}
async function del(id,perm){
  if(perm&&!confirm("本文・分析を完全に削除します。元に戻せません。よろしいですか？"))return;
  await fetch(B+"/delete/"+id,{method:"POST",headers:hdr(),
    body:JSON.stringify({permanent:perm,confirm:perm})});load()}
</script></body></html>`;

// ---------- router ----------

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "https://takehiro104toshi-cmd.github.io";
    const cors = corsHeaders(origin, allowed);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    if (url.pathname === "/admin" && request.method === "GET") {
      return new Response(ADMIN_HTML, {
        headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
    }

    if (!url.pathname.startsWith(BASE)) return json({ ok: false, error: "not_found" }, 404, cors);
    const rest = url.pathname.slice(BASE.length);

    try {
      // ---- 機械用（分析パイプライン） ----
      if (rest === "/queue" && request.method === "GET") {
        if (!machineAuth(request, env)) return json({ ok: false, error: "unauthorized" }, 401, cors);
        const limit = Math.min(parseInt(url.searchParams.get("limit") || "20", 10), 50);
        return handleQueue(env, limit);
      }
      if (rest.startsWith("/analysis/") && request.method === "POST") {
        if (!machineAuth(request, env)) return json({ ok: false, error: "unauthorized" }, 401, cors);
        return handleAnalysisPost(request, env, rest.slice("/analysis/".length));
      }
      if (rest === "/derived" && request.method === "GET") {
        if (!machineAuth(request, env)) return json({ ok: false, error: "unauthorized" }, 401, cors);
        return handleDerived(env);
      }

      // ---- 人間用（スマホUI / 管理画面） ----
      if (!(await humanAuth(request, env))) return json({ ok: false, error: "unauthorized" }, 401, cors);

      if (rest === "/intake" && request.method === "POST") {
        const r = await handleIntake(request, env);
        return new Response(r.body, { status: r.status, headers: { ...Object.fromEntries(r.headers), ...cors } });
      }
      if (rest.startsWith("/status/") && request.method === "GET") {
        const id = rest.slice("/status/".length);
        const metaRaw = await env.INSIGHT_KV.get(`meta:${id}`);
        if (!metaRaw) return json({ ok: false, error: "not_found" }, 404, cors);
        return json({ ok: true, item: stripPrivateFields(JSON.parse(metaRaw)) }, 200, cors);
      }
      if (rest === "/list" && request.method === "GET") {
        const items = (await listMetas(env, false)).map(stripPrivateFields);
        return json({ ok: true, items }, 200, cors);
      }
      if (rest.startsWith("/delete/") && request.method === "POST") {
        const r = await handleDelete(request, env, rest.slice("/delete/".length));
        return new Response(r.body, { status: r.status, headers: { ...Object.fromEntries(r.headers), ...cors } });
      }
      if (rest.startsWith("/memo/") && request.method === "POST") {
        const r = await handleMemo(request, env, rest.slice("/memo/".length));
        return new Response(r.body, { status: r.status, headers: { ...Object.fromEntries(r.headers), ...cors } });
      }
      if (rest.startsWith("/reanalyze/") && request.method === "POST") {
        const r = await handleReanalyze(env, rest.slice("/reanalyze/".length));
        return new Response(r.body, { status: r.status, headers: { ...Object.fromEntries(r.headers), ...cors } });
      }
      return json({ ok: false, error: "not_found" }, 404, cors);
    } catch (e) {
      // 本文・Secretをエラーへ含めない（種別のみ）
      return json({ ok: false, error: "internal_error" }, 500, cors);
    }
  },
};
