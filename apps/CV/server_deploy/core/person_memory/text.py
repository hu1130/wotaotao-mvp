"""Deterministic text normalization shared by memory storage and retrieval."""

from __future__ import annotations

import hashlib
import re


_WORD_RE = re.compile(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]+")
_SENSITIVE_RE = re.compile(
    r"(?:密码|口令|验证码|身份证|银行卡|信用卡|病历|诊断|token|api[_ -]?key|secret|password)",
    re.IGNORECASE,
)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in _WORD_RE.findall((text or "").casefold()):
        if "\u4e00" <= word[:1] <= "\u9fff":
            if len(word) == 1:
                tokens.append(word)
            else:
                tokens.extend(word[index : index + 2] for index in range(len(word) - 1))
                tokens.extend(word[index : index + 3] for index in range(len(word) - 2))
        else:
            tokens.append(word)
    return list(dict.fromkeys(tokens))


def normalized_fact_key(content: str) -> str:
    normalized = " ".join((content or "").casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def contains_sensitive_content(content: str) -> bool:
    return bool(_SENSITIVE_RE.search(content or ""))
