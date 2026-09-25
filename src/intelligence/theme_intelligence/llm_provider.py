"""P6-B7E — 狭い provider protocol と offline 実装（FakeProvider / RecordedProvider）。純。network・資格情報なし。

provider が受け取るのは `GenerationInput`（明示的に組んだ生成入力）だけで、返すのは raw の応答文字列だけである。
data root・authority store・B3 / B5C の追記 API・Theme / relation / review store・資格情報には触れられない。
provider は authority を持たない（`PROVIDER_HAS_NO_AUTHORITY`）。

失敗は `ProviderError(kind)` で表す（有界な語彙。本文を持たない）。自動 retry は provider も呼び出し側も行わない。

実 provider（SDK・network・API key）はこの gate の外であり、ここには存在しない。
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Callable, List, Mapping, Optional, Protocol

from .llm_generation_input import GENERATION_INPUT_DIGEST_PREFIX, GenerationInput

PROVIDER_HAS_NO_AUTHORITY = "a provider receives one generation input and returns text; it holds no authority capability"
_DIGEST_RE = re.compile(rf"^{GENERATION_INPUT_DIGEST_PREFIX}_[0-9a-f]{{24}}$")


class ProviderFailureKind(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"          # 一時的に使えない（retry は範囲外の運用判断）
    TIMEOUT = "TIMEOUT"
    FAILURE = "FAILURE"                  # 合成 / その他の一時的な失敗
    INPUT_MISMATCH = "INPUT_MISMATCH"    # 記録済み応答の束縛外の入力（integrity）


class ProviderError(Exception):
    """provider の失敗。detail に応答・入力の本文を入れない。"""

    def __init__(self, kind: ProviderFailureKind, detail: str = "") -> None:
        super().__init__(f"{kind.value}: {detail}" if detail else kind.value)
        self.kind = kind
        self.detail = detail


class GenerationProvider(Protocol):
    """生成 1 回ぶんの呼び出し口。provider / model / 生成設定の識別子は監査 record にだけ入る。"""

    provider_ref: str
    model_ref: str
    generation_config_ref: str

    def generate(self, generation_input: GenerationInput) -> str:
        ...


def _check_input(generation_input: object) -> GenerationInput:
    if not isinstance(generation_input, GenerationInput):
        raise ProviderError(ProviderFailureKind.INPUT_MISMATCH, "a provider takes a GenerationInput")
    return generation_input


class FakeProvider:
    """test 用の programmable provider。振る舞いは constructor の引数だけで決まる（環境・時計・store を読まない）。"""

    def __init__(self, *, response: Optional[str] = None, respond: Optional[Callable[[GenerationInput], str]] = None,
                 failure: Optional[ProviderFailureKind] = None, provider_ref: str = "fake_provider",
                 model_ref: str = "fake_model", generation_config_ref: str = "fake_config") -> None:
        if sum(value is not None for value in (response, respond, failure)) != 1:
            raise ValueError("a fake provider has exactly one behavior: response, respond or failure")
        self._response, self._respond, self._failure = response, respond, failure
        self.provider_ref, self.model_ref, self.generation_config_ref = provider_ref, model_ref, generation_config_ref
        self.calls: List[str] = []                       # 受け取った生成入力の digest（呼び出し回数の確認用）

    def generate(self, generation_input: GenerationInput) -> str:
        generation_input = _check_input(generation_input)
        self.calls.append(generation_input.digest())
        if self._failure is not None:
            raise ProviderError(self._failure, "scripted failure")
        if self._respond is not None:
            return self._respond(generation_input)
        return self._response  # type: ignore[return-value]


class RecordedProvider:
    """記録済み応答の offline replay。応答は生成入力の digest に束縛される（別の入力へは返さない）。"""

    def __init__(self, recordings: Mapping[str, str], *, provider_ref: str = "recorded_provider",
                 model_ref: str = "", generation_config_ref: str = "recorded_config") -> None:
        if not isinstance(recordings, Mapping) or not all(
                isinstance(k, str) and _DIGEST_RE.match(k) and isinstance(v, str) for k, v in recordings.items()):
            raise ValueError("recordings map generation input digests to raw response text")
        self._recordings = dict(recordings)
        self.provider_ref, self.model_ref, self.generation_config_ref = provider_ref, model_ref, generation_config_ref
        self.calls: List[str] = []

    def generate(self, generation_input: GenerationInput) -> str:
        generation_input = _check_input(generation_input)
        digest = generation_input.digest()
        self.calls.append(digest)
        if digest not in self._recordings:
            raise ProviderError(ProviderFailureKind.INPUT_MISMATCH, "no recording is bound to this generation input")
        return self._recordings[digest]


__all__ = ["FakeProvider", "GenerationProvider", "PROVIDER_HAS_NO_AUTHORITY", "ProviderError", "ProviderFailureKind",
           "RecordedProvider"]
