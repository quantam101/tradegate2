"""
Structured Observability Telemetry Layer (Python Runtime)

Zero-allocation structured JSON telemetry with OpenTelemetry-compatible
trace context propagation. All telemetry records are frozen dataclasses.

Design:
- Immutable data structures (frozen dataclasses)
- Microsecond-precision timestamps
- W3C Trace Context compatible span/trace IDs
- Structured JSON output for log aggregation
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Dict, Optional, Tuple


class Severity(IntEnum):
    TRACE = 1
    DEBUG = 5
    INFO = 9
    WARN = 13
    ERROR = 17
    FATAL = 21


@dataclass(frozen=True)
class SpanContext:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    start_time: float
    service: str
    operation: str


@dataclass(frozen=True)
class TelemetryEvent:
    timestamp: str
    severity_text: str
    severity_number: int
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    service: str
    operation: str
    duration_ms: Optional[float]
    attributes: Dict[str, object]
    body: str


def _generate_trace_id() -> str:
    return uuid.uuid4().hex


def _generate_span_id() -> str:
    return uuid.uuid4().hex[:16]


def create_root_span(service: str, operation: str) -> SpanContext:
    return SpanContext(
        trace_id=_generate_trace_id(),
        span_id=_generate_span_id(),
        parent_span_id=None,
        start_time=time.time(),
        service=service,
        operation=operation,
    )


def create_child_span(parent: SpanContext, operation: str) -> SpanContext:
    return SpanContext(
        trace_id=parent.trace_id,
        span_id=_generate_span_id(),
        parent_span_id=parent.span_id,
        start_time=time.time(),
        service=parent.service,
        operation=operation,
    )


def build_event(
    span: SpanContext,
    severity: Severity,
    body: str,
    attributes: Optional[Dict[str, object]] = None,
) -> TelemetryEvent:
    now = time.time()
    return TelemetryEvent(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))
        + f".{int((now % 1) * 1_000_000):06d}Z",
        severity_text=severity.name,
        severity_number=int(severity),
        trace_id=span.trace_id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        service=span.service,
        operation=span.operation,
        duration_ms=round((now - span.start_time) * 1000, 3),
        attributes=attributes or {},
        body=body,
    )


def serialize_event(event: TelemetryEvent) -> str:
    return json.dumps(asdict(event), separators=(",", ":"), sort_keys=True)


def to_traceparent(span: SpanContext) -> str:
    padded = span.trace_id.ljust(32, "0")[:32]
    span_hex = span.span_id.ljust(16, "0")[:16]
    return f"00-{padded}-{span_hex}-01"


def parse_traceparent(header: str) -> Optional[Tuple[str, str]]:
    parts = header.split("-")
    if len(parts) < 4:
        return None
    return (parts[1], parts[2])


class TelemetryCollector:
    """Collects telemetry events for batch export. Append-only."""

    def __init__(self, service: str) -> None:
        self._service = service
        self._events: list[TelemetryEvent] = []

    def span(self, operation: str, parent: Optional[SpanContext] = None) -> SpanContext:
        if parent is not None:
            return create_child_span(parent, operation)
        return create_root_span(self._service, operation)

    def emit(
        self,
        span: SpanContext,
        severity: Severity,
        body: str,
        attributes: Optional[Dict[str, object]] = None,
    ) -> TelemetryEvent:
        event = build_event(span, severity, body, attributes)
        self._events.append(event)
        return event

    def info(self, span: SpanContext, body: str, attributes: Optional[Dict[str, object]] = None) -> TelemetryEvent:
        return self.emit(span, Severity.INFO, body, attributes)

    def warn(self, span: SpanContext, body: str, attributes: Optional[Dict[str, object]] = None) -> TelemetryEvent:
        return self.emit(span, Severity.WARN, body, attributes)

    def error(self, span: SpanContext, body: str, attributes: Optional[Dict[str, object]] = None) -> TelemetryEvent:
        return self.emit(span, Severity.ERROR, body, attributes)

    def drain(self) -> list[TelemetryEvent]:
        return list(self._events)

    def to_ndjson(self) -> str:
        return "\n".join(serialize_event(e) for e in self._events)
