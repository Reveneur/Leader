"""The Audit Agent (spec section 9.11) as a plain logging/assertion helper.

Every module that could silently violate exam integrity — future data
leaking into a decision, a missing hourly row, a rewritten transaction —
calls into this module so the violation is both loud (raised) and recorded
(an audit_events row survives even if the caller swallows the exception).
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy.orm import Session

from database.models import AuditEvent
from database.repositories import add_audit_event


class FutureDataError(RuntimeError):
    """Raised when a decision would use market data timestamped after the
    decision moment — the one integrity violation this system must never
    allow, per spec section 3 and section 9.11.
    """


class Auditor:
    def __init__(self, session: Session, run_id: str | None = None) -> None:
        self.session = session
        self.run_id = run_id

    def log(
        self,
        event_type: str,
        description: str,
        severity: str = "INFO",
        metadata: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            run_id=run_id or self.run_id,
            timestamp=dt.datetime.now(dt.timezone.utc),
            event_type=event_type,
            severity=severity,
            description=description,
            metadata_json=json.dumps(metadata, default=str) if metadata else None,
        )
        return add_audit_event(self.session, event)

    def assert_not_future(
        self,
        data_timestamp: dt.datetime,
        decision_timestamp: dt.datetime,
        context: str,
    ) -> None:
        """Guards against using data that was not yet available at the
        moment a decision was made. This must be called before any candle,
        price, or score is used to make a BUY/SELL/HOLD decision.
        """
        if data_timestamp > decision_timestamp:
            self.log(
                event_type="future_data_used",
                description=(
                    f"{context}: data timestamped {data_timestamp.isoformat()} "
                    f"used for a decision at {decision_timestamp.isoformat()}"
                ),
                severity="CRITICAL",
            )
            raise FutureDataError(
                f"{context}: refusing to use data from {data_timestamp} "
                f"for a decision made at {decision_timestamp}"
            )

    def error(self, event_type: str, description: str, metadata: dict[str, Any] | None = None) -> None:
        self.log(event_type, description, severity="ERROR", metadata=metadata)

    def warning(self, event_type: str, description: str, metadata: dict[str, Any] | None = None) -> None:
        self.log(event_type, description, severity="WARNING", metadata=metadata)
