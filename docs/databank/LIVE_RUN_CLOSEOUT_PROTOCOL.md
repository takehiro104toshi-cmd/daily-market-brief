# LIVE_RUN_CLOSEOUT_PROTOCOL — live workflow の完了待機と証拠取得（2026-09-01）

Automated Closeout で GitHub Actions の live run を使う際の手順を固定する。
**無期限待機を禁止**し、`trigger → bounded polling → completed detection →
evidence retrieval` の順で必ず終端させる。

## 0. きっかけとなった実測（Phase 3-B / p2d-market-pilot run #18）

run #18 自体は **success**（5分22秒、全ステップ成功、evidenceも正常生成）だったが、
完了を待つクライアント側のshellが終わらなかった。

原因は待機ループの**完了判定が常に偽になっていた**こと:

```
# NG: 実行環境から api.github.com への素のHTTPは 403 で拒否される。
#     status が取れないため until ループが永久に回る。
until [ "$(curl -sS .../actions/runs/<id> | jq -r .status)" = "completed" ]; do
  sleep 20
done
```

実測（同一環境で再現）:

```
http_code=403
{"message":"GitHub access is not enabled for this session. ..."}
status field -> None
```

`None != "completed"` のため、run が終わってもループは抜けない。
**「応答が取れない」と「まだ完了していない」を区別していなかった**ことが本質。

## 1. 完了判定に使ってよい経路

live run の状態取得は、**セッションに許可されたGitHub API経路**
（Claude Code の GitHub tooling / 認証済みクライアント）で行う。
素の `curl https://api.github.com/...` は本環境では 403 になるため使わない。

取得するのは最低限これだけ:

| 項目 | 用途 |
|---|---|
| `status` | `queued` / `in_progress` / `completed` |
| `conclusion` | `success` / `failure` / `cancelled` / `timed_out` |
| `run_started_at` / `updated_at` | 実測duration |
| job の `steps[]` | どのstepで止まったか |

## 2. bounded polling（必須）

待機は**必ず上限付き**にする。上限は対象workflowの `timeout-minutes` から決める
（job自体がその時間で必ず終端するため、それを超えて待つ意味がない）。

```
max_wait = workflow の timeout-minutes + 2分（キュー待ち・後処理の余裕）
interval = 20〜30秒
```

Automated Closeout が待機する **live validation / pilot workflow** の上限:

| workflow | timeout-minutes | 待機上限の目安 |
|---|---|---|
| `p1c-live-validation.yml` | 10 | 12分 |
| `p2a-e2e-pilot.yml` | 10 | 12分 |
| `p2d-market-pilot.yml` | 15 | 17分 |
| `p2h-jquants-light.yml` | 20 | 22分 |

`tests/intelligence/test_live_run_closeout.py` が、これらのworkflowの全jobに
`timeout-minutes` が宣言されていること（＝待機上限が計算可能であること）と、
本ドキュメントの表が実ファイルと一致していることを機械的に固定する。

**本番workflow `daily-market-brief.yml` は本protocolの対象外**（Automated Closeout
がその完了を待機することはない）。なお観測として、同workflowの `generate-report`
jobには `timeout-minutes` が無い（`deploy-pages` は20分）。CLAUDE.mdルール15により
本番workflow・GitHub Pagesは依頼が無い限り変更しないため、**変更していない**。
上限付与が望ましいと考えるが、判断は監督者に委ねる（提案のみ）。

## 3. 完了判定のルール

- **応答が取れない場合は「未完了」と見なさない**。取得失敗として数え、
  連続失敗が閾値（例: 3回）に達したら**待機を打ち切り**、原因調査へ移る。
- `status == "completed"` を検出したら直ちに待機を終了し、`conclusion` を読む。
- 上限に達したら待機を終了する。**そこから待ち続けない**。
  未完了のまま上限に達した事実をそのまま報告する。

## 4. evidence retrieval

`completed` を検出したら、ログから pilot marker 行だけを取得する
（全文を持ち歩かない）。

| phase | marker |
|---|---|
| P2-G.1 TOPIX | `::P2G1_TOPIX::` |
| P2-G.2 V2 | `::P2G2_*::` |
| P2-H Light | `::P2H_*::` |
| Phase 3-A Fact | `::P3A_INPUT/FACTS/REPLAY/SNAPSHOT/QUERY/QUALITY::` |
| Phase 3-B Context | `::P3B_INPUT/CONTEXTS/SNAPSHOT/TOP/ALIGNMENT/QUERY::` |
| Phase 3-B pre-flight | `::P3B_JQFACT::` |

marker行はいずれも**秘密値を含まない設計**（`tests/intelligence/
test_secret_hygiene.py` が固定）。ログをそのまま報告へ貼ってよい。

## 5. 禁止事項

- 無期限の完了待機（`gh run watch` 相当・上限なしの `until` ループ）
- 完了検出のためだけの新規live run起動
- 変更が無いのに live run を回すためのempty commit
- 失敗を確認しないままの「成功」報告
