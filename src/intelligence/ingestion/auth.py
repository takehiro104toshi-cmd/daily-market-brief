"""Runtime credential注入（Phase 1-D / 監督者DESIGN CORRECTION 1）。

architecture:

    Persisted FetchRequest（Secretなし——型レベルで資格情報ヘッダ拒否を維持）
        ↓
    CredentialResolver（環境変数等から解決。コード・YAMLへSecretを書かない）
        ↓
    Ephemeral Transport Request（Secretはメモリ内のみ）
        ↓
    HttpTransport（UrllibTransport auth_headers_provider）

規律（SECRET MUST NEVER BE PERSISTED）:
- serialization禁止・JSONL禁止・RawItem禁止・FetchAttempt禁止・logging禁止・
  error detail禁止・URL保存時redact（redact_urlは従来通り全保存経路に適用）。
- resolverが返すのは**送信ヘッダのみ**。FetchRequest/FetchAttemptへは決して載らない。

P1-Dでは枠組みのみ（EDINET/e-Stat等の本格credential runtimeはP1-E以降）。
"""
from __future__ import annotations

import os
from typing import Callable, Mapping, Protocol, runtime_checkable

from .model import FetchRequest


@runtime_checkable
class CredentialResolver(Protocol):
    """source_id → 送信専用ヘッダ（空dict=認証不要）。Secret値はメモリ内のみ。"""

    def headers_for(self, source_id: str) -> Mapping[str, str]:  # pragma: no cover
        ...


class EnvCredentialResolver:
    """環境変数から資格情報を解決するresolver。

    mapping例: {"edinet_disclosures": ("Ocp-Apim-Subscription-Key", "EDINET_API_KEY")}
    → source_id=edinet_disclosuresの送信時のみ、環境変数EDINET_API_KEYの値を
      指定ヘッダ名で付与する。環境変数が未設定なら付与しない（エラーにしない——
      AUTH_REQUIRED挙動はサーバ応答で観測される）。
    """

    def __init__(self, mapping: Mapping[str, tuple[str, str]]) -> None:
        self._mapping = dict(mapping)

    def headers_for(self, source_id: str) -> Mapping[str, str]:
        entry = self._mapping.get(source_id)
        if entry is None:
            return {}
        header_name, env_var = entry
        value = os.environ.get(env_var, "")
        return {header_name: value} if value else {}


def make_auth_headers_provider(
    resolver: CredentialResolver,
) -> Callable[[FetchRequest], Mapping[str, str]]:
    """UrllibTransport(auth_headers_provider=...) へ渡すアダプタ。"""

    def provider(request: FetchRequest) -> Mapping[str, str]:
        return resolver.headers_for(request.source_id)

    return provider
