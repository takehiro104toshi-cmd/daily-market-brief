"""P12-A2 — network の拒否の guard（A2 は networkless。loopback は P11 の readiness の検査の間だけ許す）。

- `NetworkPolicy(allow_loopback)`: external は常に拒む（policy で許す欄は無い）。
- `network_guard(policy)`: 文脈の中で `socket.socket.connect` ・`connect_ex` ・`socket.create_connection` ・`socket.getaddrinfo`（DNS）
  を差し替え、loopback 以外の宛先を `AutomationError("INTERRUPTED", "NETWORK_DENIED")` で止める。`urllib` ・`http.client` は
  これらの上に乗るので同じく止まる。読み込み済みの J-Quants の client ／ transport の class の構築も止める（実用の範囲）。
  出る時に全て元に戻す。拒んだ試みの回数を数える（宛先は記録しない）。
"""
from __future__ import annotations

import socket
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from .failure_codes import AutomationError

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class NetworkPolicy:
    allow_loopback: bool = False


class NetworkDenied(AutomationError):
    def __init__(self) -> None:
        super().__init__("INTERRUPTED", "NETWORK_DENIED")


def _host_of(address: Any) -> Any:
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return address


def _is_loopback(host: Any) -> bool:
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    return isinstance(host, str) and host.split("%", 1)[0] in LOOPBACK_HOSTS


class network_guard:                                                                   # noqa: N801 - context manager
    """`with network_guard(policy) as guard:` — guard.denied は拒んだ試みの数。"""

    def __init__(self, policy: NetworkPolicy) -> None:
        if not isinstance(policy, NetworkPolicy):
            raise AutomationError("SCHEMA_INVALID", "NETWORK_POLICY")
        self.policy = policy
        self.denied = 0
        self._saved: List[Tuple[Any, str, Any]] = []

    def _allowed(self, host: Any) -> bool:
        return self.policy.allow_loopback and _is_loopback(host)

    def _deny(self) -> None:
        self.denied += 1
        raise NetworkDenied()

    def __enter__(self) -> "network_guard":
        guard = self
        real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
        real_create, real_getaddrinfo = socket.create_connection, socket.getaddrinfo

        def connect(sock: Any, address: Any) -> Any:
            if not guard._allowed(_host_of(address)):
                guard._deny()
            return real_connect(sock, address)

        def connect_ex(sock: Any, address: Any) -> Any:
            if not guard._allowed(_host_of(address)):
                guard._deny()
            return real_connect_ex(sock, address)

        def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
            if not guard._allowed(_host_of(address)):
                guard._deny()
            return real_create(address, *args, **kwargs)

        def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
            if not guard._allowed(host):
                guard._deny()
            return real_getaddrinfo(host, *args, **kwargs)

        def refuse_construction(*_args: Any, **_kwargs: Any) -> None:
            guard._deny()

        patches: List[Tuple[Any, str, Any]] = [(socket.socket, "connect", connect), (socket.socket, "connect_ex", connect_ex),
                                               (socket, "create_connection", create_connection),
                                               (socket, "getaddrinfo", getaddrinfo)]
        for module_name, module in list(sys.modules.items()):                           # 読み込み済みの J-Quants の client だけ
            if module is None or "jquants" not in module_name:
                continue
            for attr, value in list(vars(module).items()):
                if isinstance(value, type) and value.__module__ == module_name and ("Client" in attr or "Transport" in attr):
                    patches.append((value, "__init__", refuse_construction))
        for target, name, replacement in patches:
            self._saved.append((target, name, target.__dict__.get(name) if isinstance(target, type) else getattr(target, name)))
            setattr(target, name, replacement)
        return self

    def __exit__(self, *_exc: Any) -> None:
        for target, name, original in reversed(self._saved):
            if original is None and isinstance(target, type):
                delattr(target, name)
            else:
                setattr(target, name, original)
        self._saved.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {"allow_loopback": self.policy.allow_loopback, "denied": self.denied}


__all__ = ["LOOPBACK_HOSTS", "NetworkDenied", "NetworkPolicy", "network_guard"]
