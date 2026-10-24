# PHASE 13 — A5-0R: WINDOWS VALIDATION PLAN（文書だけ ・本記録は実行を承認しない）

P13-A5 の Windows の検証の計画を、監督の審査（P13-A5-0 の設計 PASS ・refined Option B を計画の方向として承認）の後に、守られた
文書だけの契約として記録する。本記録は **計画**であり、Windows の結果は無い（全ての項目は未実行）。A5-T ・A5-W ・A6 は HOLD、
helper の作成 ・実行は HOLD、実の private な source への access は HOLD。runtime ・凍結の契約 ・凍結の pin は変えない。

| 項目 | 値 |
|---|---|
| gate | `P13-A5-0R`（文書だけ） |
| 基準の HEAD | `f6145ac2902ab95ec20affecb11300d6176b9d5a`（Product Roadmap v2.0 の commit） |
| 監督の決定 | P13-A5-0 の設計の審査 PASS ・refined Option B は計画の方向として承認 ・本記録は GO。A5-T ・A5-W ・A6 ・helper ・S2 は HOLD |
| 継承の順序 | **Windows の検証は A6 の前**（P12.5 の継承の順序 ・本記録は変えない） |
| 結果 | Windows の結果は無い。本記録のどの値も実行の結果ではない |

## 1. 権限の区分（混ぜない）

- **継承した凍結の契約**: P12.5 の closeout §5 の 6（P13-A5 Windows private validation ・repo の外の helper ・read-only の source ・
  使い捨ての vault ・前後の manifest ・P12-A6 の様式）と 7（P13-A6 final freeze ・記録 ・registry ・guard）。P12.5-A0 §10 の受け入れ試験
  8（export の安全）・9（crash-safe な公開）・11（実機の read-only の private validation）。P12.5-A0 §6.1（同期 ・plugin ・目印の方針）。
- **既存の P13 の記録**: A3 の記録 §1（成分の安全 ・ACL は A5 で検証）・§4（置き換えない移動）・§6（Windows の安全と既知の限界）・§8。
  A4b の記録 §1（別名 ・TOCTOU は A5）・§2（plugin の実物の id ・bare な note の名前の衝突は A5）・§5（残った lock の人の手順は A5 で検証）・
  §11（Windows ・P13-A5 の限界）。roadmap の記録 §13 ・§24 ・§26。
- **runtime の前提**: Windows の分岐は置き換えない rename だけ（`memory_store.py` ・`projection_store.py` の `_move_without_replacing`）・
  directory の fsync は Windows では行われない（`_fsync_directory`）・所有は `st_ino` が 0 でないことを要する ・reparse point は
  `st_file_attributes` で判定 ・Windows に `O_NOFOLLOW` は無い（lstat と開いた handle の identity の一致で補う）・lock の解放は `finally`
  の中（process の異常な終了では残る）。
- **新しい提案（計画の方向として承認 ・各段は別の GO）**: core と任意の Obsidian の track の分離 ・A5-T の特性の記録の後の固定 ・
  A5-W の 2 段（S1 ・S2）・人の回復の手順 ・A6 の条件つきの主張。

本記録は継承した義務を黙って変えない。狭い主張を提案する箇所は、要る決定を名指す。

## 2. 作業の包み（全て HOLD）

| 包み | 目的 | 前提 | 成果 |
|---|---|---|---|
| A5-T | Windows での試験の移植と特性の記録（T-01 〜 T-06） | 所有者の環境の事実 ・別の GO | 失敗の分類 ・Windows の mutation の列 ・分類の文字列 ・差の説明 ・別の承認の試験の変更 |
| A5-W | 隔離した Windows NTFS での A3 ・A4b の検証（W-01 〜 W-20） | A5-T ・helper の承認 ・別の GO | KEY=VALUE の報告 ・手元だけの manifest |
| 任意の Obsidian の track | app の表示と統合（O-01 〜 O-06） | product の提案 ・監督の明示の scope の決定 | 本記録では承認しない |
| A6 | 凍結の判断と証拠の包み | A5-W の core の全ての BLOCKING の項目 ・§9 の主張の審査 | 凍結の記録 ・registry ・guard |

環境の記号: **S1** ＝ 隔離した Windows ・local NTFS ・合成の source だけ。**S2** ＝ S1 ＋ 読み取りだけの実の P9 ／ P10 の source（§7 ・HOLD）。

## 3. A5-W の必須の core の試験（W-01 〜 W-20）

全ての項目は、番兵の directory の manifest の不変と、報告に private な値が無いことも要する。A6 の列: BLOCKING（A6 を止める）・
CONDITIONAL（主張の条件 ・不合格なら対応する主張は無い）・RECORD_ONLY（記録だけ ・除外の文で扱う）・DECISION_REQUIRED（決定まで止める）。

| ID | 契約の参照 | 脅威 ／ 失敗の様態 | 環境 | 手順 → 期待 | 不変量 | 証拠 | STOP | A6 |
|---|---|---|---|---|---|---|---|---|
| W-01 | A3 §6（file の identity）・A4b §1 | `st_ino` が 0 ／ 不安定で所有 ・root の identity を確かめられない | S1 | 基準の volume で file を作り ・開き直し ・同じ volume で rename し ・別の process で stat する → identity が 0 でなく安定 ・`st_nlink` は 1 | 所有を検証できる | `FS_TYPE` ・`INO_NONZERO` ・`INO_STABLE` | identity が 0 ／ 不安定（その volume は対象外） | BLOCKING |
| W-02 | A3 §4 ・A4b §4 ・Windows の分岐 | rename が既存の版 ／ 証拠 ／ generation を置き換える | S1 | 公開の前に移動先を作っておく → `FileExistsError` が衝突 ／ FAILED として出る ・既存の byte は不変 | 決して上書きしない | code の件数 ・manifest の差 0 | 置き換えが 1 件でも起きる | BLOCKING |
| W-03 | A3 §6 ・A4b §11 | pointer の置換の失敗 ・部分 | S1 | `publication.json` と `p13-memory.md` を通常と、W-08 の handle を持たせて置き換える → pointer は常に前か後の byte ・失敗は fail closed | pointer は前か後 | pointer の digest | 部分の pointer ・FAILED の回が pointer を変えた | BLOCKING |
| W-04 | A3 §6（durability） | directory の fsync ができず rename の永続が分からない | S1 | directory の fsync が行われないことを観測して記録する | 主張しない | `DIR_FSYNC` | directory の fsync の成功を主張する記録 | RECORD_ONLY |
| W-05 | A3 §1（ACL は A5 で検証） | 継承した ACL が他の主体に読ませる | S1 | 作った root の ACL を読み取りだけで照会し、主体の種類の件数だけを記録する（変更しない） | 機密性は置き場所に依る | 主体の種類の件数 | 予定の S2 の置き場所に広い主体 | CONDITIONAL |
| W-06 | A3 §1 ・§6 ・A4b §1 ・§11 | 祖先 ・root ・entry の reparse point ・junction ・symlink で root の外へ出る | S1 | junction（管理者は要らない）・directory ／ file の symlink（Developer Mode が要る）・任意で mount point ・OneDrive の placeholder を置く → 拒否（`ROOT_UNSAFE_COMPONENT` ／ `UNSAFE_ENTRY`）・外への書き込み 0 | root の外へ出ない | 拒否の code ・番兵の manifest | 受け入れ ・外への書き込み | BLOCKING |
| W-07 | A4b §2 ・A3 の `_read_file` | hard link が外の file と同じ実体を指す | S1 | `generated/` と `projection/` の hard link → `UNSAFE_ENTRY`。A3 の root の hard link の振る舞いを targeted に試す（A3 の読みは `st_nlink` を確かめない）。**A3 の hard link の振る舞いは未解決の境界の懸念**であり、無害な例外として受け入れていない | link を通して書かない | code ・A3 の観測 | link を通した書き込み ・A3 の懸念の未決 | BLOCKING |
| W-08 | A3 §6 ・A4b §11 | 開いた handle の共有違反 | S1 | 削除の共有の無い handle を pointer ・staging の元 ・解放の時の lock に段ごとに持たせる → PermissionError は時間の内に fail closed ・状態は不変 ・handle を閉じた後に収束 | fail closed ・停止しない | code ・所要の時間 | 停止 ・成功の報告 | BLOCKING |
| W-09 | A3 §6 ・A4b §1 ・§11 | 大小 ・8.3 の短い名前 ・UNC ・`\\?\` の接頭辞の別名で重なりの検査を迂回 | S1 | root と保護の root を別名の形で渡す → 重なりの拒否 ／ `ROOT_INVALID`。大小だけ違う entry → `UNKNOWN_ENTRY` | root は重ならない | code ・短い名前の有無 | 別名の受け入れ | BLOCKING |
| W-10 | A3 §1 ・§6 ・A4b §11 | ASCII 以外の path ・代替 data stream ・末尾の点 ／ 空白 ・MAX_PATH | S1 | ASCII 以外の基準の folder で動く ・代替 data stream と末尾の点 ／ 空白の形 → `ROOT_INVALID` ・260 文字の近くの root の長さを試す | 別名の拒否 ・長い path は fail closed | 最大の root の長さ ・long path の設定 | 別名の受け入れ ・fail closed でない長い path の失敗 | BLOCKING |
| W-11 | A4b §11 | 容量の preflight が利用者の quota を反映しない | S1 | `disk_usage` の値の健全さと quota の有無を記録する | 空きの不足は fail closed | quota の試験の有無 | 整数でない ／ 負の空きで preflight が通る ・空きの不足が fail closed でない | RECORD_ONLY |
| W-12 | A3 §5 ・A4b §5 ・P12-A6 の先例 | process の間の lock の競合 | S1 | 2 つの process が N 回競う → 勝つのは常に 1 つ ・負けた側は何も書かない | 相互排他 | 勝ち ／ 負けの件数 | 2 つが勝つ | BLOCKING |
| W-13 | A4b §6 ・P12.5-A0 §10 の 9 | 注入した例外の後の回復 | S1 | §5 の A5-T の行列を Windows で → 想定外 0 | 収束か設計どおりの HOLD | 場合ごとの分類の文字列 | FAILED_UNEXPECTEDLY | BLOCKING |
| W-14 | A3 §6（実機の中断）・A4b §11 ・roadmap §13 | 実際の process の終了の後の回復 | S1 | 子の process を各点の前 ／ 後で終了させる（§5）→ 許した状態だけ ・歴史は不変 | 壊さない ・失わない | 点ごとの分類 | 想定外 ・消失 | BLOCKING |
| W-15 | P12.5 の closeout §4 の 7 ・A4b §4 | 歴史の消失 | S1 | 全ての場面の前後の manifest → 前の版 ・証拠 ・generation ・試行の記録は byte 一致 | 何も消さない | manifest の差 | 意図した物の外の差 | BLOCKING |
| W-16 | A4b §5（人の手順は A5 で検証） | 人の回復が安全でない ／ 曖昧 | S1 | §6 の手順を終了の残りの種類ごとに演習する → 収束 ・quarantine の byte と sha256 は不変 | 移すだけ ・消さない | 操作の記録（値は無い） | 手順に削除が要る | BLOCKING |
| W-17 | A4b §11（Defender ・索引） | antivirus ・索引の干渉 | S1 | Defender を有効にしたまま公開 ／ NO_CHANGE を K 回 → 失敗が在れば fail closed | fail closed | 失敗の件数 | 黙った誤り | BLOCKING |
| W-18 | P12.5-A0 §6.1 ・A4b §2 | Windows で同期 ・plugin の拒否が変わる | S1 | 合成の同期 folder の名前と目印 ・合成の `.obsidian` の設定（app は無い）→ 拒否の code は不変 | 同期 ・plugin の拒否の規則は弱めない | code | 受け入れ | BLOCKING |
| W-19 | P12.5-A0 §10 の 1 | OS による出力の差（改行 ・符号化） | S1 | 同じ合成の generation → export と record の digest が Linux の基準と一致 | 決定論の byte | digest の一致 | 不一致 | BLOCKING |
| W-20 | P12.5 の closeout §5 の 6（read-only の source）・P12.5-A0 §10 の 11 | 実の source との互換 ・漏えい | S2 | A2a → A3 → A4b を使い捨ての root へ → 実の root の manifest は不変 ・privacy の走査は PASSED ・報告は集計だけ | 実の root は読みだけ ・private な値は機械の外へ出ない | 手元だけの manifest の hash ・集計の件数 | 実の root の変化 ・走査の一致 | DECISION_REQUIRED |

local NTFS は **提案した初期の対象であり検証済みの能力ではない**。A3 ・A4b の Windows の振る舞いは未検証のままである。

## 4. Windows の code の道（A3 ・A4b）と stdlib で確立できること

| 領域 | A3（`memory_store.py`） | A4b（`projection_store.py`） | Windows の stdlib で確立できるか | できない時 |
|---|---|---|---|---|
| 置き換えない rename | Windows の分岐は `os.rename` だけ | 同じ | できる（移動先が在れば `FileExistsError`）| — |
| pointer の置換 | `os.replace` | `os.replace` | process の終了の下の前か後は試せる ・電源断の不可分は試せない | 除外（C-07） |
| directory の fsync | Windows では行われない | 同じ | できない | 除外（C-07）・読みは fail closed のまま |
| identity と所有 | `st_dev` ／ `st_ino`（0 は検証できない） | 同じ ＋ `st_nlink` | NTFS では W-01 で確かめる ・幅と出所は Python の版と file system で違う | その volume は STOP ・対象外 |
| ACL の継承 | POSIX の mode は効かない | 同じ | 読み取りだけの照会で観測できる ・stdlib では強制できない | 置き場所の規則 ・広い主体なら S2 を STOP |
| reparse ・junction ・symlink | 全ての成分の lstat の reparse の bit | 同じ | 検査の時点では確かめられる | TOCTOU の除外（C-08） |
| hard link | `st_nlink` を確かめない | 拒否 | 確かめられる | A3 は未解決の境界の懸念（W-07 ・C-14） |
| 共有違反 | `OSError` で fail closed | 同じ | fail closed は試せる ・違反の不在は試せない | W-08 ・W-17 |
| 大小 ・8.3 ・UNC の別名 | `normcase` ・`realpath` ・identity の重なり | 同じ | 検査の時点では確かめられる | TOCTOU の除外 |
| Unicode ・path の長さ | 正規化しない | 同じ ＋ 生成の名前は ASCII だけ | 確かめられる | 最大の root の長さを記録 |
| 代替 data stream ・末尾の点 ／ 空白 | `WINDOWS_ALIAS` | 同じ | 確かめられる | — |
| 容量 ・quota | — | `_free_bytes` だけ | 一部（quota を反映した空きは出ないと見込む ・所有者の Python で確かめる） | 除外（C-13） |
| 異常な終了での lock の解放 | `finally` は飛ぶ ・lock は残る | 2 つの lock が残る | 試せる（W-14） | 人の手順 ・奪取は無い |

**STOP（弱めて除外にしない）**: identity が 0 ／ 不安定 ・検出されない reparse point ／ 別名 ・使い捨ての root の外への書き込み ・
歴史の置き換え ・部分の pointer ・出力 ／ 報告の private な値 ・実の root の変化（S2）・共有違反での停止 ・想定外の分類。

## 5. 故障の行列の移植（A5-T）

- **受理した POSIX の基準は変えない**: 42 の mutation の点 ・6 つの故障の形 ・252 の場合（`RECOVERY_MATRIX`）。
- **Windows の mutation の数は UNKNOWN**（特性の記録まで確定しない）。予約の mkdir が無いという見込みは仮説であり、確定ではない。
- **期待の数を失敗に合わせて書き換えない**。期待を実行の時に観測から計算しない。

| ID | 内容 | 出力 | STOP |
|---|---|---|---|
| T-01 | 既存の P13 の suite を Windows で変えずに走らせる（特性の記録 ・修正は無い） | 失敗の種類ごとの件数（symlink の権限 ・42 の点の assertion ・POSIX の前提） | 実の root ・vault への access |
| T-02 | 記録の代理で A4b ・A3 の無故障の公開の mutation の列を列挙し POSIX と比べる | 点の列と差 | 説明できない差 |
| T-03 | 注入した例外の行列（前 ／ 後 ／ 切れ × 1 つ ／ 2 つ目の故障）を Windows で特性の記録だけ行う | 場合ごとの分類と trace | FAILED_UNEXPECTEDLY |
| T-04 | 各 Windows の点を操作 ・種類 ・順で POSIX の点に対応させ、分類の差ごとに code の道の原因を書く | 差の説明 | 原因の無い差 |
| T-05 | 試験だけの変更（別の承認）: POSIX の表は不変のまま Windows の期待の表を足す ・platform ごとの数の assertion ・権限に応じた skip | 固定した Windows の期待 | runtime の変更が要る |
| T-06 | Windows の複製で独立の負の control: 16 の強化の control ・nt で POSIX の予約の道を強いる ・置き換える rename ・PermissionError を成功とみなす ・Windows の表の 1 つの値の反転 ・終了の harness の 1 つの kill の省略 | 全て捕まる | 捕まらない control |

- 分類: AUTO_RECOVERED（runtime だけで収束）・HELD_AS_DESIGNED（安全な HOLD ・明示の保存 ・特定できない残り）・
  MANUAL_INTERVENTION_REQUIRED（§6 の手順が要った ・その後の収束も自動とは数えない）・FAILED_UNEXPECTEDLY（不変量の破れ）。
- **注入した例外**（`finally` は走る）と **実際の process の終了**（`finally` は走らない）は別の行列であり、混ぜない。終了の行列は
  親が子の process を n 番目の mutation の前 ／ 後で止めて終了させ、新しい process で分類する。lock を取る前の終了は AUTO_RECOVERED、
  取った後は MANUAL_INTERVENTION_REQUIRED（lock ・残りの種類ごと）を見込むが、特性の記録の後に別に固定する。

## 6. 人の回復の手順（設計だけ ・実行できる道具は無い）

前提: 何も公開しない。**process の生存は lock から証明できない**（pid を持たない設計）。所有者が runtime の process が無いことを
確かめても、**再起動だけでは片付けを承認しない**（再起動は生存の不確かさを減らすだけ ・各介入は明示の承認を要する）。

| 段 | 操作 | 規則 |
|---|---|---|
| 1 証拠の保存 | 両方の root の読み取りだけの before の manifest（相対の path の種類 ・大きさ ・sha256 ・file の identity ・file の種類 ・`st_nlink`）を root の外に作る | manifest の前に操作しない |
| 2 診断 | 直前の HOLD ／ REFUSED の code と、将来の読み取りだけの残りの診断（別の gate）で、lock ・決定論の作業中の file ・FAILED の一時 file ・未知に分ける | 未知 ／ 外来の entry は無期限の HOLD |
| 3 lock の検証 | lock の byte が lock の record として読めること ・範囲 ・操作 ・file の種類が正規の file ・`st_nlink` が 1 ・identity を記録 | 読めない ・正規でない lock は無期限の HOLD |
| 4 lock の移動 | 所有者の明示の承認の後に、code が名指す 1 つの lock だけを同じ volume の両方の root の外の quarantine へ **移す**（消さない） | lock の盲目的な除去 ・stale lock の奪取は無い |
| 5 残り | code が名指す残りだけ（FAILED の一時 file は決して採らない ・決定論の byte が分かっていて違う file）を移す。byte 一致の続きに使える record は残す | 証拠 ・版は編集しない ・消さない |
| 6 runtime の明示の操作 | `PRESERVE_STAGING` ・`PRESERVE_EMPTY_RESERVATION`（A4b）・`preserve_interrupted_staging` ・`preserve_publication_pointer`（A3）は API だけ | 手で移さない |
| 7 検証 | after の manifest の差が意図した移動と完全に一致 ・quarantine の identity ・byte ・sha256 が不変 | 他の差は STOP |
| 8 承認と記録 | 介入ごとの明示の承認と、操作 ・種類 ・digest ・結果の記録（private な値 ・path ・時刻は手元だけ） | 記録の無い操作は改竄として扱う |
| 9 再試行 | 1 回だけ再試行する。新しい code なら診断し直す ・同じ code が続けば無期限の HOLD と escalation | — |

**無期限の HOLD**: 未知 ／ 外来の entry ・改竄 ／ 破損した確定の証拠 ・pointer ／ 版の改竄 ・root の identity の不一致 ・reparse point ／
別名の検出 ・ACL の懸念 ・manifest の食い違い ・読めない lock ・繰り返す code ・曖昧な状態。

**検証の状態**: lock ・切れた record ・FAILED の一時 file を移す操作は Linux の合成の試験でだけ安全と確かめた（狭い模擬）。**Windows では
何も検証していない**（W-16 で演習する）。

## 7. 実の source と合成の source（S2）

| | S2: 読み取りだけの実の P9 ／ P10 ＋ 使い捨ての出力 ＋ manifest | S1 だけ: 全て合成 |
|---|---|---|
| 契約 | 継承の文（private validation ・read-only の source）と P9-A5 ／ P10-A5 の先例に最も文字どおり | filesystem の項目は満たす。S1 だけで A6 へ進むには監督の明示の決定による狭い主張が要る（契約の改訂ではない） |
| 安全 | 低い: 使い捨ての memory の root は実の private な識別子を持つ（A1 の entry）・vault は件数だけ | 最も高い: private な data は無い |
| 証拠 | A2a → A1 → A3 → A4b の実の data の形 ・実の root の不変 ・実から作った出力の privacy の走査 | NTFS の意味 ・故障 ・終了 ・回復 |

- **実の source の検証の義務は残す**。**S2 は所有者の別の承認と privacy の審査まで HOLD**。
- S2 を行う時: S1 の全ての BLOCKING の項目の後 ・実の root は読み取りだけで写す（隔離した環境が望ましい）・使い捨ての root は所有者
  だけの同期しない場所（W-05）・報告は集計だけ ・検証の root の保持 ／ 削除は所有者が決める（private な識別子を含む）。
- S2 を行わないなら、A6 の記録は「Windows の検証は合成の source だけ ・実の source との互換は検証していない」と書き、監督の明示の決定を要する。

## 8. 任意の Obsidian の track（product の提案）

core の A5 に残す（app は要らない）: export の filesystem の安全（W-02 ・W-06 〜 W-10 ・W-15）・合成の設定による拒否の規則（W-18）・
OS をまたぐ byte の決定論（W-19）。

| ID | 内容 |
|---|---|
| O-01 | 生成した note の表示 |
| O-02 | bare な link の解決と名前の衝突の振る舞い（A4b §2） |
| O-03 | `.p13-staging` ・`.p13-interrupted` の dot folder の扱い |
| O-04 | 入れた plugin の実物の id と拒否の一覧の照合（A4b §2 ・network の取得は無い） |
| O-05 | app が file を開いている間の共有違反 |
| O-06 | mobile の同期（範囲の外 ・設計で拒む） |

- 本 track は **product の提案であり既存の契約の検査の免除ではない**（承認されていない）。
- A4b の記録の「P13-A5 で検証」の記述（O-02 ・O-04）を本 track へ移すには **監督の明示の scope の決定**が要る。決定まで A5 の義務のまま。
- O-04 が通るまで **実の vault への export は支持しない**。同期 ・plugin の拒否の規則は弱めない。

## 9. A6 の保証の主張（条件つき ・別々の状態）

状態: SYNTHETIC_ONLY（合成の試験だけ）・CONDITIONAL（条件の W の項目が全て通った時だけ）・UNSUPPORTED（主張しない）・
OUT_OF_SCOPE（範囲の外）・DECISION_REQUIRED（決定まで主張しない）。

| ID | 主張 | 状態 | 条件 ／ 注 |
|---|---|---|---|
| C-01 | 合成の POSIX の試験の被覆 | SYNTHETIC_ONLY | Linux の suite ・252 の場合 ・負の control |
| C-02 | Windows NTFS の filesystem の安全 | CONDITIONAL | W-01 ・W-02 ・W-03 ・W-06 〜 W-10 ・W-12 ・W-15 ・W-18 ・W-19 |
| C-03 | ACL による機密性 | UNSUPPORTED | 強制は無い ・置き場所の規則だけ ・広い主体は潜在的に blocking |
| C-04 | 中断した公開からの回復 | CONDITIONAL | W-13 ・W-14 |
| C-05 | 人の手の回復 | CONDITIONAL | W-16 |
| C-06 | 無人の運用 ／ 回復 | UNSUPPORTED | 定時の書き込みの前に統治された回復の設計が要る |
| C-07 | 電源断の durability | UNSUPPORTED | directory の fsync が無い ・読みは fail closed |
| C-08 | TOCTOU の安全 | UNSUPPORTED | 検査の時点だけ |
| C-09 | 実の source との互換 | DECISION_REQUIRED | S2（W-20）・所有者の承認と privacy の審査 |
| C-10 | Obsidian の app の表示 ・統合 | OUT_OF_SCOPE | 任意の track ・実の vault への export は支持しない |
| C-11 | 実の private root への配備 | OUT_OF_SCOPE | 配備の gate は無い |
| C-12 | mobile の同期 ・mobile の access | OUT_OF_SCOPE | 同期は設計で拒む |
| C-13 | quota を反映した容量 | UNSUPPORTED | W-11 は記録だけ |
| C-14 | A3 の hard link の扱い | DECISION_REQUIRED | 未解決の境界の懸念（W-07） |

- **除外は凍結を自動では認めない**。STOP の条件が覆う完全性 ・機密性の未解決は潜在的に blocking。
- A6 は BLOCKING の全ての W の項目と、C-09 ・C-14 の決定と、本表の審査を要する。

## 10. 隔離した Windows の環境（提案 ・未構築）

- 隔離: Windows Sandbox か VM の snapshot（使い捨て ・同期の account ・資格情報 ・network が無い）が望ましい。無ければ host の専用の folder。
- 構成（`<base>` ・local NTFS の固定の disk ・同期の root の外 ・repository の外）: `synthetic-sources/`（凍結の試験の builder で作る）・
  `private/`（composition root）・`vault/`（人の様式の目印と合成の `.obsidian` の設定 ・app は無い）・`quarantine/` ・`evidence/` ・`sentinel/`。
- helper: stdlib だけ ・repository の外 ・transfer 専用の branch と SHA256（P11-A5 ・P12-A6 の先例）・runtime に import しない。
  **helper の作成 ・実行は HOLD**。
- 証拠: KEY=VALUE の行だけ（例の形 `INO_STABLE=<value>`）。path ・利用者の名前 ・SID ・時刻 ・識別子は出さない。manifest は手元だけ。
- 片付け: 自動の片付けは無い。監督の受理の後に所有者が `<base>` を保存 ／ 除去する。
- 所有者に求める非機密の事実（まだ command は求めない）: Windows の edition と build ・Sandbox ／ Hyper-V の有無 ・Python の版と
  architecture ・予定の volume の file system ・OneDrive の folder の転送の下か ・Developer Mode ／ symlink の権限 ・管理者の権限の有無 ・
  long path の設定 ・Defender の常時保護と他の antivirus ・Windows Search の索引の対象か ・locale ・空き容量 ・実の P9 ／ P10 の root が
  同じ機械に在るか（有無と volume の種類だけ）・helper の受け渡しの git の有無。

## 11. 将来の gate の file ／ 試験の範囲（承認しない）

| gate | 範囲 |
|---|---|
| A5-0R（本記録） | 本文書 ・`phase13_runtime_registry.py`（`PHASE13_DOCS`）・`test_market_memory_boundary.py`（文書の tuple ・registry の digest ・本記録の guard）・CHANGELOG |
| A5-T | (a) 所有者の特性の記録の実行（T-01 〜 T-04 ・repository は変えない）。(b) 試験だけの変更（T-05 ・P13 の store ／ build の試験 ・CHANGELOG ・登録済みの P13 の試験なので registry は変えない） |
| A5-W | repository の外の helper で所有者が実行（S1 の後に承認があれば S2）・repository は変えない |
| A5 の是正 | 欠陥ごとに別の承認。A3 の欠陥は凍結の `P13_A3` の pin を開け直す（runtime ・registry の認可 ・pin ・試験 ・文書 ・CHANGELOG）。A4b の欠陥は新しい是正の gate。影響する W の項目をやり直す |
| A6 | 凍結の記録 ・registry の anchor の定数と全ての P13 の runtime の pin ・boundary の guard ・CHANGELOG ・証拠の包み（Linux と Windows の結果 ・helper の SHA256 ・集計の報告 ・観察 ・§9 の主張） |

## 12. 禁止

- 実の root への書き込み（S2 でも読みだけ）。
- lock の盲目的な除去 ・stale lock の奪取 ・自動の片付け ・証拠 ／ 版の削除 ・編集。
- 破壊的な試験（実の root ・実の vault ・同期の client ・ACL ・local の設定の変更を伴うもの）。
- 実の private な source ・実の Obsidian の vault への本記録による access。
- 同期 ・plugin の拒否の規則を弱めること。
- 期待の数を失敗に合わせて書き換えること。

## 13. roadmap への影響

| 項目 | 契約の blocking の条件 | 任意の予定の順 |
|---|---|---|
| P12-B0 ・L0 ・M0 ・H0 ・S0 | 無い | 並行できる |
| H1（合成の iPhone の prototype） | 無い | 並行できる |
| P13-E | roadmap §13: A6 が前提。A5-W の所見は証拠の store の設計の技術的な入力 | P13-E0 の設計を並行にするなら監督の順序の決定 |
| P13-K ・P13-R ・H2 ・P14 | P13-E を経て | — |
| 定時 ／ 無人の Market Memory の書き込み | 統治された回復の設計（C-06） | — |

任意の Obsidian の track は iPhone を先にする道のどれの前提でもない。

## 14. 所有者 ・監督の決定と残る blocker

1. S2 を要するか、狭い主張を受け入れるか（§7）。
2. 実行の環境（Sandbox ・VM ・host）。
3. 支持する volume の範囲（local NTFS だけ）。
4. ACL: 置き場所の規則を受け入れるか、強制の gate を要するか。
5. C-07 ・C-08 ・C-13 の除外の受け入れ（凍結を自動では認めない）。
6. A5-T の特性の記録の後の固定の方法と試験の変更の範囲。
7. repository の外の helper と transfer の branch の承認。
8. v1 の人の手順の採用 ・将来の読み取りだけの診断 ・無人の書き込みの前の統治された回復。
9. 任意の Obsidian の track の正式な承認と、A4b の記述（O-02 ・O-04）の scope の決定。
10. A3 の hard link の懸念（C-14）の扱い。
11. A3 の欠陥が見つかった時の pin の開け直しの方針。

実行を始める前の blocker: 1 ・2 ・7 と §10 の環境の事実。

## 15. 本記録の承認の範囲

本記録は計画の記録だけであり、**A5-T ・A5-W ・A6 は HOLD**、**helper の作成 ・実行は HOLD**、S2 は HOLD。本記録は実行 ・helper ・
実の source ・runtime の変更 ・凍結の契約の改訂のいずれも承認しない。Market Memory v1 は凍結していない。
