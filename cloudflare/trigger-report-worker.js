/**
 * Cloudflare Worker: daily-market-brief のワンタップ再生成中継（v3.4）
 *
 * 役割:
 *   GitHub Pages上のHTMLから呼ばれ、GitHub Actions の workflow_dispatch API を叩いて
 *   レポート生成ワークフローを起動する「安全な中継役」。GitHub Token は Cloudflare
 *   Worker の Secret（環境変数）にのみ保管し、レスポンスにもHTMLにも一切出さない。
 *   HTML側はこの Worker のエンドポイントURLを知っているだけで、Tokenは知らない。
 *
 * 必要な Secret / 変数（Cloudflareダッシュボード または wrangler で設定）:
 *   - GITHUB_TOKEN          … Fine-grained PAT（Actions: Read and write / Contents:
 *                             Read and write、対象repoは daily-market-brief のみ）。※Secret必須
 *   - GITHUB_OWNER          … 例: takehiro104toshi-cmd
 *   - GITHUB_REPO           … 例: daily-market-brief
 *   - GITHUB_WORKFLOW_FILE  … 例: daily-market-brief.yml
 *   - ALLOWED_ORIGIN        … 例: https://takehiro104toshi-cmd.github.io（省略時は下記既定値）
 *   - WORKFLOW_REF          … ディスパッチ対象ブランチ（省略時は "main"）
 *
 * API:
 *   POST /trigger
 *     成功: { "ok": true,  "message": "workflow dispatched" }
 *     失敗: { "ok": false, "error": "..." }
 *   OPTIONS /trigger … CORSプリフライト
 *   それ以外のパス/メソッド … 404 / 405
 *
 * CORS: 許可Originは ALLOWED_ORIGIN（既定 https://takehiro104toshi-cmd.github.io）のみ。
 *       それ以外のOriginからのリクエストは拒否する。
 *
 * セキュリティ:
 *   - GITHUB_TOKEN はソースコードに直書きしない（env 経由でのみ参照）。
 *   - Token はレスポンスボディ・ヘッダー・ログに一切含めない。
 *   - GitHub API のエラー詳細は要約のみ返す（Tokenを含み得る生レスポンスは返さない）。
 */

const DEFAULT_ALLOWED_ORIGIN = "https://takehiro104toshi-cmd.github.io";

function corsHeaders(origin, allowedOrigin) {
  // 許可Originに完全一致した場合のみACAOを返す（不一致なら付けない＝ブラウザがブロック）。
  const headers = {
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
  if (origin && origin === allowedOrigin) {
    headers["Access-Control-Allow-Origin"] = allowedOrigin;
  }
  return headers;
}

function json(body, status, extraHeaders) {
  return new Response(JSON.stringify(body), {
    status: status,
    headers: Object.assign({ "Content-Type": "application/json" }, extraHeaders || {}),
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const allowedOrigin = env.ALLOWED_ORIGIN || DEFAULT_ALLOWED_ORIGIN;
    const origin = request.headers.get("Origin") || "";
    const cors = corsHeaders(origin, allowedOrigin);

    // CORSプリフライト
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }

    if (url.pathname !== "/trigger") {
      return json({ ok: false, error: "not found" }, 404, cors);
    }
    if (request.method !== "POST") {
      return json({ ok: false, error: "method not allowed" }, 405, cors);
    }

    // 許可Origin以外は拒否（ブラウザ以外の直叩き・別サイトからの呼び出しを防ぐ）。
    if (origin && origin !== allowedOrigin) {
      return json({ ok: false, error: "origin not allowed" }, 403, cors);
    }

    // 必須Secret/変数の存在チェック（Token値そのものはレスポンスに出さない）。
    const token = env.GITHUB_TOKEN;
    const owner = env.GITHUB_OWNER;
    const repo = env.GITHUB_REPO;
    const workflow = env.GITHUB_WORKFLOW_FILE;
    const ref = env.WORKFLOW_REF || "main";
    if (!token || !owner || !repo || !workflow) {
      return json({ ok: false, error: "worker not configured" }, 500, cors);
    }

    const apiUrl =
      "https://api.github.com/repos/" + owner + "/" + repo +
      "/actions/workflows/" + workflow + "/dispatches";

    try {
      const gh = await fetch(apiUrl, {
        method: "POST",
        headers: {
          "Authorization": "Bearer " + token,
          "Accept": "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "daily-market-brief-worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: ref }),
      });

      // 204 No Content = ディスパッチ成功
      if (gh.status === 204) {
        return json({ ok: true, message: "workflow dispatched" }, 200, cors);
      }

      // 失敗時はステータスに応じた要約だけを返す（Tokenを含み得る生ボディは返さない）。
      let reason = "github api error (" + gh.status + ")";
      if (gh.status === 401 || gh.status === 403) {
        reason = "authentication failed (check token permissions)";
      } else if (gh.status === 404) {
        reason = "workflow or repository not found";
      } else if (gh.status === 422) {
        reason = "invalid ref or workflow not dispatchable";
      }
      return json({ ok: false, error: reason }, 502, cors);
    } catch (e) {
      return json({ ok: false, error: "network error contacting github" }, 502, cors);
    }
  },
};
