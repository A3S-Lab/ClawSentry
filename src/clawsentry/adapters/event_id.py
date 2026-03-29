"""Stable event_id generation — shared across all adapters.

Implements the hash-based event_id scheme from 02-unified-ahp-contract.md section 6.1.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional


def generate_event_id(
    source_framework: str,
    session_id: str,
    event_subtype: str,
    occurred_at: str,
    payload: dict[str, Any],
) -> str:
    """Generate a stable 24-char hex event_id via sha256 hash.

    Uses: sha256(source_framework:session_id:event_subtype:occurred_at:payload_digest)[:24]
    """
    payload_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    raw = f"{source_framework}:{session_id}:{event_subtype}:{occurred_at}:{payload_digest}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def generate_event_id_with_priority(
    source_framework: str,
    session_id: str,
    event_subtype: str,
    occurred_at: str,
    payload: dict[str, Any],
    *,
    approval_id: Optional[str] = None,
    run_id: Optional[str] = None,
    source_seq: Optional[int] = None,
) -> str:
    """Generate event_id with OpenClaw priority chain.

    Priority: approval_id > runId:seq > hash fallback.
    """
    if approval_id:
        raw = f"{source_framework}:{approval_id}:{event_subtype}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    if run_id and source_seq is not None:
        raw = f"{source_framework}:{run_id}:{source_seq}:{event_subtype}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    return generate_event_id(
        source_framework, session_id, event_subtype, occurred_at, payload,
    )
