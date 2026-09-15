"""Compass Context Engine（Phase 3-B）。

Phase 3-Aのatomic Factを、Morning Compassが利用可能な
**structured investment context** へ変換する層。

DATA → OBSERVATION → FACT → **CONTEXT** → NARRATIVE(3-C) → OUTLOOK → COMPASS

ContextはNarrativeではない。自然言語の相場解説・投資推奨・因果主張を含まない。
LLMに依存せず**決定論的**に生成する。
"""
