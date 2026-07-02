"""EDINET（金融庁 電子開示システム）の公開書類一覧APIから開示情報を取得する。

https://disclosure.edinet-fsa.go.jp/api/v2/documents.json は金融庁が公開している
書類一覧APIであり、ログイン不要で一般公開されている（書類本文の取得は行わず、
提出者名・書類種別・提出日時・書類管理番号のみを扱う）。

APIキーについて:
    EDINET APIは無料のAPIキー登録が案内される場合がある。環境変数
    EDINET_API_KEY が設定されていればリクエストに付与し、未設定でも
    そのまま取得を試みる（取得できない場合は空リストで「取得不可」扱いとする）。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from ..utils import SourceRegistry, safe_get

logger = logging.getLogger("market_brief")

DOCUMENTS_URL = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"


@dataclass
class EdinetDocument:
    filer_name: str
    doc_description: str
    submit_datetime: str
    doc_id: str


def fetch_edinet_documents(
    sources: SourceRegistry,
    target_date: Optional[date] = None,
    limit: int = 10,
    documents_url: Optional[str] = None,
) -> List[EdinetDocument]:
    """documents_url を指定すると既定のEDINET APIエンドポイントを上書きできる
    （テストで到達不能なローカルアドレスに差し替える用途を想定）。"""
    documents_url = documents_url or DOCUMENTS_URL
    target_date = target_date or date.today()
    params = {"date": target_date.strftime("%Y-%m-%d"), "type": 2}
    api_key = os.environ.get("EDINET_API_KEY")
    if api_key:
        params["Subscription-Key"] = api_key

    resp = safe_get(documents_url, params=params)
    if resp is None:
        return []

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.warning("EDINET応答の解析に失敗しました: %s", exc)
        return []

    results: List[EdinetDocument] = []
    for item in (payload.get("results") or [])[:limit]:
        filer_name = (item.get("filerName") or "").strip()
        doc_description = (item.get("docDescription") or "").strip()
        submit_datetime = (item.get("submitDateTime") or "").strip()
        doc_id = (item.get("docID") or "").strip()
        if not doc_id:
            continue
        results.append(
            EdinetDocument(
                filer_name=filer_name or "取得不可",
                doc_description=doc_description or "取得不可",
                submit_datetime=submit_datetime,
                doc_id=doc_id,
            )
        )

    if results:
        sources.add("EDINET 書類一覧", documents_url, "適時開示・有価証券報告書等")
    return results
