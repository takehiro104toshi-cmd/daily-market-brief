"""P10-A2 — Personal Profile と Attention の記録をまたぐ不変条件（純 ・自動の書き換えなし ・好みの推測なし）。

時点 T の像（各 root の `reviewed_at <= T` の最大の seq）で:
1. ACTIVE な Personal Profile は高々 1 つ（退役の後の新しい profile は別の root）。
2. 生きている Attention（FOCUS ・MUTE）は P9 の対象の root ごとに高々 1 つ（同じ対象に FOCUS と MUTE が同時に無い）。
   CLEARED の後は同じ対象に新しい root を作れる。

意図して検査しないこと:
- Profile の除外と Attention の組（除外 ＋ FOCUS ・除外 ＋ MUTE は有効）。除外は個人の制約 ／ 文脈、FOCUS ／ MUTE は表示の意図で、
  矛盾する authority ではない。表示（「profile で除外」の組 ・印の保持）は A4 の見直しの view が決める。印を消す ・拒む ・変える
  ことはしない（Attention は発行体を持たず、A2 は P9 を読まない）。
- 参照の実在（対象の root ・見た revision）。A2 は構文だけ ・実在は A4（A1 の adapter）。

`check_personal_world` は全 revision の審査の瞬間ごとに像を検査する（後の revision の追加が過去の時点を壊すことも検出する）。記録を
書き換える ・状態を自動で変える ・Attention を導く関数は無い。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Mapping, Sequence, Tuple

from .attention_model import LIVE_ATTENTION_STATES, AttentionRevision, validate_attention_chain
from .profile_model import PersonalProfileRevision, ProfileStatus, validate_profile_chain
from .revision_model import check_instant, group_chains, require, states_at

ProfileChains = Dict[str, Tuple[PersonalProfileRevision, ...]]
AttentionChains = Dict[str, Tuple[AttentionRevision, ...]]


def check_personal_snapshot(profile_chains: Mapping[str, Tuple[PersonalProfileRevision, ...]],
                            attention_chains: Mapping[str, Tuple[AttentionRevision, ...]], at: datetime) -> None:
    """時点 T の像の不変条件（1 ・2）。違えば fail closed。"""
    instant = check_instant(at, "at")
    active = [root for root, head in states_at(profile_chains, instant).items() if head.status is ProfileStatus.ACTIVE]
    require(len(active) <= 1, "MULTIPLE_ACTIVE_PROFILES", str(len(active)))
    live_by_target: Dict[str, str] = {}
    for root, head in states_at(attention_chains, instant).items():
        if head.state in LIVE_ATTENTION_STATES:
            require(head.target_root_id not in live_by_target, "DUPLICATE_LIVE_ATTENTION", head.target_root_id)
            live_by_target[head.target_root_id] = root


def check_personal_world(profile_revisions: Sequence[PersonalProfileRevision],
                         attention_revisions: Sequence[AttentionRevision]) -> Tuple[ProfileChains, AttentionChains]:
    """全ての鎖を検査し、全 revision の審査の瞬間ごとに像の不変条件を検査する（純 ・入力の順に依らない）。"""
    profile_chains = group_chains(profile_revisions, validate_profile_chain, PersonalProfileRevision)
    attention_chains = group_chains(attention_revisions, validate_attention_chain, AttentionRevision)
    instants = sorted({r.reviewed_at for chain in (*profile_chains.values(), *attention_chains.values())
                       for r in chain})
    for instant in instants:
        check_personal_snapshot(profile_chains, attention_chains, instant)
    return profile_chains, attention_chains


__all__ = ["AttentionChains", "ProfileChains", "check_personal_snapshot", "check_personal_world"]
