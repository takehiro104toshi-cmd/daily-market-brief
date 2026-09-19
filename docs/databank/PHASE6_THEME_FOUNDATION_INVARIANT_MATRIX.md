# Phase 6 — Theme Foundation Invariant Matrix（P6-A4d）

A1（1〜25）/ A2（26〜60）/ A3（61〜97）の不変条件と、それを守る層・test・状態の対応表。

status の語彙: **PROVEN**（test で証明）/ **STRUCTURAL**（field / 語彙 / import が存在しないことで構造的に保証。専用 test は
その不在を固定）/ **DEFERRED**（後続 phase の責務）/ **NOT_APPLICABLE**。これに加え、A4d の E2E で見つかった
contract / implementation mismatch に関わる行は **BLOCKED**（証明できていない。修正 gate まで PROVEN と書かない）とする。

layer: MODEL（A4a）/ STORE（A4b）/ RESOLVER（A4c）/ E2E（A4d）/ FUTURE。test 名の module 略号:
model ＝ test_theme_model、ident ＝ test_theme_identity、evid ＝ test_theme_evidence、gov ＝ test_theme_governance_model、
bnd ＝ test_theme_import_boundary、store ＝ test_theme_store、corr ＝ test_theme_store_corruption、
ops ＝ test_theme_store_operations、res ＝ test_theme_resolver、fac ＝ test_theme_resolver_facets、
e2e ＝ test_theme_foundation_e2e、rep ＝ test_theme_foundation_replay、fail ＝ test_theme_foundation_failures。

## A4d で見つかった BLOCKER（凍結 runtime は未変更。strict xfail で再現を固定）

| id | 事象 | 契約 | 再現 test | 最小修正候補 | 影響範囲 |
|---|---|---|---|---|---|
| **A4D-1** | store が identity core（driver / channel / domain / subject）の置換を同一 root の revision として **受理**する（`ThemeObservation.build` で直接組んだ observation を append できる。純 helper `revise_observation` だけが拒否） | A3 §7（append で IDENTITY_CORE_CHANGED を拒否）、§23（load で INVALID_HISTORY）、A2 §2.3 | fail::test_store_rejects_identity_core_change_within_a_root | `store._validate_observation_chain` の非 genesis 分岐で `identity_core_fingerprint(predecessor) != identity_core_fingerprint(obs)` なら `_reject(..., "IDENTITY_CORE_CHANGED")`（`from .fingerprint import identity_core_fingerprint`。約 6 行）。resolver `_resolve` にも同じ検査を INVALID_HISTORY として追加（約 6 行）。`HISTORY_REASONS` に code 追加 | store.py / resolver.py のみ。canonical bytes・id・A4a 不変。boundary test の許可 import に `.fingerprint` は既にある。store test 1 本追加 |
| **A4D-2** | METADATA_CORRECTION_APPROVED（related record が metadata id）を含む store が **再 open できない**（load 順 roots → observations → governance → metadata のため、governance の intra 検査で metadata がまだ無く GOVERNANCE_REFERENCE_MISSING ＝ INVALID_HISTORY）。append 自体は受理される | A3 §3（固定 load 順）と §10（METADATA_CORRECTION_APPROVED は metadata を参照）の組合せ。後続 authority への参照は cross pass で検査すべき（A4b §31 の 2 pass 方針） | e2e::test_metadata_correction_approval_survives_reload | `_validate_event` の related_observations 検査を、METADATA_CORRECTION_APPROVED の場合だけ `_validate_event_results`（cross pass）へ移す（約 10 行）。append 時は両 pass が走るので挙動不変 | store.py のみ。既存 test 不変。corruption test 1 本追加 |
| **A4D-3** | 宣言済みだが RootRecord が **未作成**の result root を解決すると UNKNOWN_ROOT で PENDING_EVENT / lineage が付かない。後日 RootRecord が書かれると同じ T で ROOT_AFTER_CUTOFF ＋ PENDING_EVENT ＋ lineage になる ＝ T より後の record が過去 T の診断を変える | A3 §13（T 後の record は結果に影響しない）、A4c §32（result root 側でも PENDING_EVENT を返す） | rep::test_declared_result_root_diagnostics_do_not_depend_on_later_root_record、fail::test_declared_but_uncreated_result_root_shows_pending_event、rep::test_future_record_matrix[merge_root-C-merge_declared_incomplete] | resolver `_resolve` の `root is None` 分岐でも、T で eligible な宣言 event（root_id ∈ result_roots）を集めて PENDING_EVENT ＋ lineage を付ける（ROOT_AFTER_CUTOFF 分岐と同じ約 6 行） | resolver.py のみ。state facet は不変（診断のみ） |

いずれも凍結 file の変更を要するため A4d では修正せず、BLOCKER_FOUND として報告する。

## A1 — semantic authority（1〜25）

| # | 意味 | layer | tests | status | note |
|---|---|---|---|---|---|
| 1 | Theme ≠ keyword / topic（label だけでは成立しない） | MODEL | model::test_mechanism_requires_each_component_type_and_a_consequence, model::test_observation_structural_requirements | PROVEN | 機構 4 component・scope・invalidation condition が必須 |
| 2 | Theme ≠ 単一 event | RESOLVER | evid::test_qualification_single_event_frame_does_not_qualify | PROVEN | Q4: PERIOD_FRAME single_* は DOES_NOT_QUALIFY |
| 3 | Theme ≠ ContextItem | MODEL | evid::test_context_item_kind_is_prohibited_and_ref_prefix_enforced | PROVEN | CONTEXT_ITEM は kind に存在せず PROHIBITED_EVIDENCE_KIND |
| 4 | Theme ≠ Narrative（prose は authority ではない） | MODEL | model::test_observation_field_inventory_excludes_metadata_lifecycle_and_prediction, e2e::test_a1_semantic_authority_traceability | STRUCTURAL | label / description / narrative field が observation に無い |
| 5 | Theme ≠ Prediction（方向・target・horizon・正誤なし） | MODEL | model::test_observation_field_inventory_excludes_metadata_lifecycle_and_prediction | STRUCTURAL | expected_change は定性 7 値のみ |
| 6 | Theme ≠ Recommendation | MODEL | evid::test_inferred_links_are_semantic_with_provenance_and_no_recommendation_fields | STRUCTURAL | weight / side / target_price field なし |
| 7 | Theme ≠ Compass rule（DNA を変えない） | E2E | bnd::test_theme_modules_import_only_core_ids_and_core_time, bnd::test_themes_is_excluded_from_production_bundle_and_no_frozen_package_imports_it | PROVEN | compass を import しない・production closure 外 |
| 8 | evidence 参照能力（id・時点・provenance） | MODEL | evid::test_attachment_round_trip_and_key, evid::test_evidence_time_and_attached_at_are_independent_fields | PROVEN | |
| 9 | 反証能力（0 件は正当） | MODEL / E2E | evid::test_qualification_is_pure_and_flags_contradiction_and_invalidation, e2e::test_checkpoints_evidence_accumulation | PROVEN | genesis は evidence 0 件で RESOLVED |
| 10 | 点時刻で再構成可能な不変履歴 | STORE / RESOLVER / E2E | e2e::test_checkpoints_*, e2e::test_restart_reload_gives_identical_results, rep::test_byte_level_replay_reproduces_authorities_and_results | PROVEN | identity core の store 側検査は 31 参照 |
| 11 | 連関 ≠ 因果（件数で class を上げない） | MODEL / RESOLVER | evid::test_evidence_supported_class_without_diversity_is_diagnosed_not_changed, evid::test_certainty_classes_carry_no_rank_or_arithmetic | PROVEN | 資格判定は診断のみ、class を変えない |
| 12 | 自動候補 ≠ reviewed Theme | MODEL | gov::test_governance_events_are_human_decisions_with_reason_and_actor | STRUCTURAL | 受理は HUMAN の governance event のみ。自動経路なし |
| 13 | reviewed ≠ production authority | E2E | bnd::test_themes_is_excluded_from_production_bundle_and_no_frozen_package_imports_it | PROVEN | production bundle guard |
| 14 | LLM 単独では evidence / 因果 / merge / reviewed / authority を確立できない | MODEL | evid::test_human_role_requires_note_and_llm_role_is_provisional, gov::test_governance_events_are_human_decisions_with_reason_and_actor | PROVEN | LLM_PROPOSAL は資格非算入、governance event を書けない |
| 15 | 反証の不在 ≠ 確証 | RESOLVER | evid::test_qualification_requires_both_diversities | STRUCTURAL | 資格判定は反証の不在を使わない（確証 field なし） |
| 16 | taxonomy slug ≠ identity | MODEL / E2E | model::test_metadata_change_does_not_touch_observation_identity, e2e::test_checkpoints_metadata_mapping_governance | PROVEN | |
| 17 | Theme は Context 無しで存在できる | E2E | e2e::test_checkpoints_evidence_accumulation | PROVEN | 代表 world は ContextItem を含まない |
| 18 | P4 / P5 を変更せず、P4 / P5 から import されない | E2E | bnd::*, production bundle guard | PROVEN | P4 diff 0・P5 unchanged を gate ごとに確認 |
| 19 | 確度 class の宣言必須、不確実性は class ＋ limitations ＋ 反証 | MODEL | model::test_observation_structural_requirements, evid::test_source_causal_claim_requires_textual_kind_and_class_requires_flag | PROVEN | |
| 20 | evidence 参照は PRIMARY / DERIVED の class を持つ | MODEL | evid::test_only_primary_observational_can_be_attached | PROVEN | authority_class 必須 |
| 21 | Compass 出力・Brief・prediction / evaluation / calibration は evidence ではない | MODEL | model::test_frozen_enum_vocabularies, evid::test_only_primary_observational_can_be_attached | PROVEN | kind 5 値のみ、NOT_THEME_EVIDENCE は拒否 |
| 22 | 同一時点・同一 source の多数の言及は複数の観測ではない | RESOLVER | evid::test_syndicated_copies_count_as_one_origin, evid::test_same_series_two_dates_is_temporal_not_source_diversity | PROVEN | |
| 23 | 企業固有 thesis は Theme 定義の外（Phase 9） | FUTURE | — | DEFERRED | 企業 thesis の構成要素は存在しない。運用は governance policy |
| 24 | 人間 decision は理由と対象を伴い履歴に残り自動では起きない | MODEL / STORE | gov::test_governance_events_are_human_decisions_with_reason_and_actor, store::test_governance_physical_references | PROVEN | |
| 25 | 却下 / 引退した候補も削除されない | STORE / RESOLVER | store::test_append_writes_exact_canonical_line_with_flush_and_fsync, fac::test_event_reversed_restores_prior_state_without_deleting_history, e2e::test_checkpoints_retired_reversed_and_merge | PROVEN | 追記専用・chain は残る |

## A2 — identity / evidence（26〜60）

| # | 意味 | layer | tests | status | note |
|---|---|---|---|---|---|
| 26 | 二層 identity（root lineage ＋ 内容住所 observation） | MODEL / E2E | ident::test_observation_identity_payload_keys_and_golden, e2e::test_a2_identity_evidence_traceability | PROVEN | A は 1 root に 6 observation |
| 27 | root id は生成 id、fingerprint は別保持 | MODEL | ident::test_root_id_is_generated_not_content_derived, model::test_new_root_id_is_opaque_generated_and_valid | PROVEN | |
| 28 | observation id は IDENTITY / SEMANTIC のみから | MODEL | ident::test_observation_identity_payload_keys_and_golden, model::test_observation_id_excludes_provenance_and_recorded_at | PROVEN | golden vector 固定 |
| 29 | 同一 id 異 bytes ＝ conflict、同一 bytes ＝ 冪等 | STORE | store::test_same_id_different_bytes_is_conflict_even_for_non_identity_fields, store::test_exact_idempotency_same_id_same_bytes | PROVEN | |
| 30 | root は evidence 蓄積・metadata・class・scope 改訂を通じて不変 | E2E | e2e::test_a2_identity_evidence_traceability, ident::test_revise_observation_allows_same_root_changes_from_a2_table | PROVEN | |
| 31 | identity core の置換は同一 root の revision として書けない | MODEL / STORE | ident::test_revise_observation_rejects_identity_core_changes, fail::test_store_rejects_identity_core_change_within_a_root（xfail） | **BLOCKED** | 純 helper は拒否するが store は受理する（A4D-1） |
| 32 | fingerprint 一致 ≠ identity、自動 merge なし | MODEL | ident::test_fingerprint_equality_is_not_identity_and_no_merge_helper_exists | PROVEN | |
| 33 | merge / split は理由・actor 付き governance 事象、root は削除されない | STORE / E2E | ops::test_merge_declaration_first_and_order_is_enforced, e2e::test_merge_semantics_e2e, e2e::test_split_semantics_e2e | PROVEN | |
| 34 | 1 root に genesis 1 つ、fork は UNRESOLVED | STORE / RESOLVER | corr::test_second_mismatching_genesis_and_wrong_root_predecessor, res::test_observation_fork_is_unresolved, fail::test_observation_fork_only_breaks_the_semantic_facet | PROVEN | |
| 35 | evidence は参照であり値・本文を複製しない | MODEL | evid::test_attachment_round_trip_and_key | STRUCTURAL | value / body field なし、excerpt は計算に使わない |
| 36 | attachment の必須 field（kind / class / ref_id / origin / 時点 / attached_at / role / provenance） | MODEL | evid::test_attachment_round_trip_and_key | PROVEN | |
| 37 | EVIDENCE_TIME ≠ ATTACHED_AT、監査時刻で代替しない | MODEL | evid::test_evidence_time_and_attached_at_are_independent_fields | PROVEN | basis 語彙に retrieved / created は無い |
| 38 | 点時刻 T の evidence は両時点 ≤ T | RESOLVER / E2E | res::test_delayed_attachment_is_invisible_before_it_was_attached, e2e::test_checkpoints_revision_delayed_evidence_and_upstream, rep::test_future_record_matrix | PROVEN | |
| 39 | evidence_time MISSING は権威 role 不可・資格非算入 | MODEL / RESOLVER | evid::test_missing_evidence_time_only_as_context, res::test_context_without_time_is_separated_from_authoritative_view | PROVEN | |
| 40 | evidence_time > attached_at は拒否 | MODEL | evid::test_evidence_time_after_attached_at_is_rejected | PROVEN | |
| 41 | authority class 4 値、資格算入は PRIMARY のみ | MODEL / RESOLVER | evid::test_only_primary_observational_can_be_attached, evid::test_qualification_excludes_context_llm_missing_and_unknown | PROVEN | |
| 42 | Compass / Brief / Signal / P5 / legacy config / LLM 出力は evidence ではない | MODEL | model::test_frozen_enum_vocabularies | PROVEN | |
| 43 | ContextItem 無しで PRIMARY だけで資格を満たせる | E2E | e2e::test_checkpoints_evidence_accumulation | PROVEN | Fact ＋ 公式文書で QUALIFIES |
| 44 | 転載 / 派生 / 判定不能は独立 origin に数えない | RESOLVER | evid::test_syndicated_copies_count_as_one_origin, evid::test_observation_and_its_fact_share_origin_and_derived_fact_is_not_independent_from_inputs, evid::test_unknown_origin_is_never_independent | PROVEN | |
| 45 | 同一 series 複数日付は temporal のみ、Q5 は両方 | RESOLVER | evid::test_same_series_two_dates_is_temporal_not_source_diversity, evid::test_qualification_requires_both_diversities | PROVEN | |
| 46 | 独立性 / 多様性は集合濃度の述語、score なし | MODEL | evid::test_diversity_helpers_are_predicates_not_scores, evid::test_qualification_without_evidence_is_candidate_and_result_has_no_score | PROVEN | |
| 47 | role 4 値、TRIGGER は metadata | MODEL | evid::test_trigger_is_a_flag_not_a_role_and_one_role_per_attachment | PROVEN | |
| 48 | 1 attachment 1 role、訂正は新 observation | MODEL / E2E | evid::test_trigger_is_a_flag_not_a_role_and_one_role_per_attachment, e2e::test_correction_and_revision_are_new_history_with_old_bytes_intact | PROVEN | |
| 49 | 反証 0 件は正当、不在は確証ではない | E2E | e2e::test_checkpoints_evidence_accumulation | PROVEN | 9 / 15 参照 |
| 50 | INVALIDATES は condition ref 必須、lifecycle を自動で変えない | MODEL | evid::test_invalidates_requires_condition_reference_and_dangling_refs_fail | PROVEN | lifecycle は未実装（P6-C） |
| 51 | role provenance 3 値、LLM_PROPOSAL は資格非算入・L2 に存在しない | MODEL / RESOLVER | evid::test_human_role_requires_note_and_llm_role_is_provisional | PROVEN | 「L2 に存在しない」の強制は P6-C の受理検査（DEFERRED 部分） |
| 52 | evidence の authority と role の真偽は独立 | E2E | e2e::test_correction_and_revision_are_new_history_with_old_bytes_intact | STRUCTURAL | 役割訂正後も attachment は PRIMARY のまま |
| 53 | 機構は型付き component、prose ではない | MODEL | model::test_mechanism_requires_each_component_type_and_a_consequence, model::test_mechanism_category_vocabulary_and_other_requires_statement | PROVEN | |
| 54 | 確度 class は observation level に 1 つ、component 平均なし | MODEL | evid::test_certainty_classes_carry_no_rank_or_arithmetic | STRUCTURAL | component に class field なし |
| 55 | expected consequence は価格 target / horizon / 正誤を持たず P5 に流入しない | MODEL / E2E | model::test_observation_field_inventory_excludes_metadata_lifecycle_and_prediction, bnd::* | STRUCTURAL | |
| 56 | entity link 3 class、INFERRED は provenance ＋ 不確実性、推奨ではない | MODEL | evid::test_entity_link_class_representations_follow_a2, evid::test_inferred_links_are_semantic_with_provenance_and_no_recommendation_fields | PROVEN | |
| 57 | mapping は別 record、identity / fingerprint / P5 / 昇格に関与しない | MODEL / E2E | model::test_mapping_round_trip_and_isolation, fac::test_mapping_supersession_and_valid_from, e2e::test_checkpoints_metadata_mapping_governance | PROVEN | |
| 58 | invalidation condition は semantic content、contradicting evidence は attachment | MODEL | model::test_observation_structural_requirements, evid::test_invalidates_requires_condition_reference_and_dangling_refs_fail | PROVEN | |
| 59 | label / description / taxonomy / alias は observation 外、変更は新 observation を生まない | MODEL / E2E | model::test_metadata_change_does_not_touch_observation_identity, e2e::test_checkpoints_metadata_mapping_governance | PROVEN | |
| 60 | fuzzy / embedding / 自動 dedup を identity に用いない | MODEL | ident::test_fingerprint_equality_is_not_identity_and_no_merge_helper_exists, bnd::test_package_contains_only_authorized_modules | STRUCTURAL | |

## A3 — persistence / revision / point-in-time（61〜97）

| # | 意味 | layer | tests | status | note |
|---|---|---|---|---|---|
| 61 | canonical 履歴は追記専用 | STORE | store::test_append_writes_exact_canonical_line_with_flush_and_fsync, bnd::test_no_io_network_clock_random_store_or_resolver_in_theme_sources | PROVEN | open mode は 'a' のみ |
| 62 | 記録済み observation の bytes は変化しない | E2E | e2e::test_correction_and_revision_are_new_history_with_old_bytes_intact, e2e::test_merge_semantics_e2e | PROVEN | |
| 63 | metadata 変更は semantic revision を生まない | E2E | e2e::test_checkpoints_metadata_mapping_governance | PROVEN | |
| 64 | semantic revision は predecessor を上書きしない | STORE / E2E | store::test_predecessor_rules, e2e::test_checkpoints_revision_delayed_evidence_and_upstream | PROVEN | |
| 65 | 点時刻状態は cutoff 以後の record を用いない | RESOLVER / E2E | rep::test_every_later_stage_leaves_earlier_checkpoints_unchanged, rep::test_future_record_matrix | **BLOCKED** | state facet は全 checkpoint で証明済み。未作成 result root の診断だけが後の RootRecord に依存（A4D-3） |
| 66 | T 前に知られ T 後に付与された evidence は T に現れない | RESOLVER / E2E | res::test_delayed_attachment_is_invisible_before_it_was_attached, e2e::test_checkpoints_revision_delayed_evidence_and_upstream | PROVEN | |
| 67 | T 前に付与され T 後の evidence_time は T に現れない | RESOLVER | res::test_evidence_view_checks_both_times_independently | STRUCTURAL | model 上は不可能（evidence_time ≤ attached_at）。独立検査を固定 |
| 68 | fork は file 順で解決されない | RESOLVER | res::test_max_recorded_at_and_physical_order_are_not_winners, corr::test_fork_on_disk_is_diagnosed_not_resolved | PROVEN | |
| 69 | fork は timestamp だけで解決されない | RESOLVER | res::test_max_recorded_at_and_physical_order_are_not_winners, fail::test_observation_fork_only_breaks_the_semantic_facet | PROVEN | |
| 70 | 破損は黙って skip されない | STORE / E2E | corr::test_corrupt_lines_are_never_skipped, fail::test_corruption_is_fail_closed_at_the_resolver_entry_point | PROVEN | |
| 71 | 同一 id 異 bytes は fail closed | STORE | corr::test_physical_duplicates, store::test_same_id_different_bytes_is_conflict_even_for_non_identity_fields | PROVEN | |
| 72 | merge は旧 root / observation / governance 履歴を保持 | E2E | e2e::test_merge_semantics_e2e, fac::test_merge_before_and_after | PROVEN | |
| 73 | split は元 root を保持 | E2E | e2e::test_split_semantics_e2e | PROVEN | |
| 74 | 上流 evidence の改訂は Theme 履歴を書き換えない | E2E | e2e::test_upstream_supersession_changes_only_dereference_status | PROVEN | |
| 75 | correction は新しい履歴を作る | E2E | e2e::test_correction_and_revision_are_new_history_with_old_bytes_intact | PROVEN | METADATA_CORRECTION_APPROVED の再 open は A4D-2 |
| 76 | SQLite は derived のみ | FUTURE | bnd::test_no_io_network_clock_random_store_or_resolver_in_theme_sources | DEFERRED | index 未実装。canonical だけで解決できることは replay で証明 |
| 77 | rebuild は network / 現在時刻を必要としない | E2E | rep::test_byte_level_replay_reproduces_authorities_and_results, bnd::* | PROVEN | |
| 78 | canonical data は repository の外、既定 fallback なし | STORE | store::test_explicit_data_root_required_and_no_repository_fallback | PROVEN | |
| 79 | MVP の writer 保証は SINGLE_WRITER のみ | STORE | store::test_single_writer_claim_matches_implementation | PROVEN | |
| 80 | governance の曖昧は UNRESOLVED として明示 | RESOLVER / E2E | fac::test_governance_fork_is_isolated_to_the_governance_facet, fail::test_governance_fork_only_breaks_the_governance_facet | PROVEN | |
| 81 | metadata の曖昧は当該 field の UNRESOLVED | RESOLVER / E2E | fac::test_label_fork_does_not_break_semantic_state, fail::test_label_fork_only_breaks_the_label_facet | PROVEN | |
| 82 | latest-wins resolver は存在しない | RESOLVER | res::test_max_recorded_at_and_physical_order_are_not_winners, store::test_no_resolver_or_latest_api, res::test_status_vocabularies_are_distinct_and_no_convenience_api | PROVEN | |
| 83 | root-breaking な semantic 変更は別 root | MODEL / E2E | e2e::test_successor_semantics_e2e, ident::test_revise_observation_rejects_identity_core_changes | **BLOCKED** | successor 経路は証明済み。store が黙った置換を拒否しない（A4D-1） |
| 84 | T 以後の merge / split / successor / 訂正は T の結果を変えない | E2E | rep::test_every_later_stage_leaves_earlier_checkpoints_unchanged, rep::test_future_record_matrix, e2e::test_checkpoints_retired_reversed_and_merge | PROVEN | state facet。診断の A4D-3 は 65 参照 |
| 85 | index の削除 / 再構築は canonical の結果を変えない | FUTURE | — | DEFERRED | index 未実装 |
| 86 | genesis は root ごとに 1 つ、RootRecord が id を固定 | STORE | store::test_genesis_validation, corr::test_second_mismatching_genesis_and_wrong_root_predecessor | PROVEN | |
| 87 | chain に沿って recorded_at 非減少 | STORE | store::test_predecessor_rules, store::test_metadata_chain_rules, store::test_mapping_chain_rules, store::test_governance_physical_references | PROVEN | |
| 88 | attached_at は root created_at 以上・observation recorded_at 以下 | STORE / MODEL | store::test_attached_at_bounds_relative_to_root, evid::test_attached_at_after_recorded_at_rejected | PROVEN | carried attachment は配分どおりなら例外（A3 §17） |
| 89 | predecessor は同一 root・同一 authority 内に物理先行 | STORE | store::test_predecessor_rules, corr::test_second_mismatching_genesis_and_wrong_root_predecessor | PROVEN | |
| 90 | governance event は observation を改変せず、承認は新 observation を指す | E2E | gov::test_correction_approvals_reference_the_approved_records, e2e::test_correction_and_revision_are_new_history_with_old_bytes_intact | PROVEN | |
| 91 | 結果 root は宣言 event を origin に持ち、宣言なしに存在しない | STORE | ops::test_merge_declaration_first_and_order_is_enforced, corr::test_result_root_without_declaring_event_is_invalid_history, ops::test_result_root_cannot_be_redeclared_or_created_as_candidate | PROVEN | |
| 92 | 未完了操作は明示状態、自動 rollback / 補完なし | STORE / RESOLVER / E2E | ops::test_merge_crash_boundaries, ops::test_split_crash_boundaries, ops::test_successor_crash_boundaries, fail::test_candidate_crash_pending_resume_e2e, fail::test_split_and_successor_partial_completion_e2e | PROVEN | subject root 側と store `pending()` で証明。未作成 result root 側の resolver 表示は A4D-3 |
| 93 | 再構成は純関数（同一 bytes・root・T → 同一出力） | RESOLVER / E2E | res::test_same_bytes_root_cutoff_give_same_result_and_input_order_is_irrelevant, rep::test_shuffled_history_gives_identical_resolutions, e2e::test_restart_in_a_separate_process_matches | PROVEN | |
| 94 | RootRecord は current_* を持たない | MODEL | model::test_root_record_field_inventory_has_no_current_state | STRUCTURAL | |
| 95 | DERIVED は canonical 行に含まれない | E2E | e2e::test_derived_values_are_recomputed_and_never_stored | PROVEN | |
| 96 | in-place migration の経路は無い | STORE | bnd::test_no_io_network_clock_random_store_or_resolver_in_theme_sources, corr::test_unsupported_schema_id_mismatch_unknown_field_and_bad_vocabulary | STRUCTURAL | 'w' / truncate / rename / replace 不在、未知 version は fail closed |
| 97 | STORE_CORRUPTION / INVALID_HISTORY / UNRESOLVED / NO_STATE は潰されない | STORE / RESOLVER | corr::test_failure_categories_are_distinct_and_pending_is_not_an_error, res::test_status_vocabularies_are_distinct_and_no_convenience_api | PROVEN | |

## 集計

| status | 件数 | 番号 |
|---|---|---|
| PROVEN | 78 | 上表の PROVEN 行（1–3, 7–11, 13–14, 16–22, 24–30, 32–34, 36–51, 53, 56–59, 61–64, 66, 68–75, 77–82, 84, 86–93, 95, 97） |
| STRUCTURAL | 13 | 4, 5, 6, 12, 15, 35, 52, 54, 55, 60, 67, 94, 96 |
| DEFERRED | 3 | 23, 76, 85 |
| BLOCKED | 3 | 31（A4D-1）, 65（A4D-3）, 83（A4D-1）。A4D-2 は 75 の注記（correction 自体は PROVEN、METADATA_CORRECTION_APPROVED を含む store の再 open が未証明） |
| NOT_APPLICABLE | 0 | — |
| 合計 | 97 | — |

（正確な内訳は各行の status 列が正。92 は PROVEN だが A4D-3 の注記を持つ。）

## 契約 traceability（A1 / A2 / A3 → E2E / structural proof）

- **A1**: semantic authority（1・4・7・13）、Theme vs Narrative（4）、vs Context（3・17）、vs Compass（7・13・18）、human
  governance（12・14・24・25）→ e2e::test_a1_semantic_authority_traceability ＋ 上表。
- **A2**: identity（26〜34）、evidence（35〜42）、二重時点（37〜40）、diversity（44〜46）、fingerprint（27・32・60）、entity
  link（56）、qualification（41・43・45）→ e2e::test_a2_identity_evidence_traceability ＋ 上表。
- **A3**: persistence（61・70・71・78・79）、revision（62〜64・75）、append-only（61）、PENDING（92）、point-in-time
  （65〜69・84・93）、merge / split / successor（72・73・83・91）→ e2e::test_a3_persistence_traceability ＋ 上表。
