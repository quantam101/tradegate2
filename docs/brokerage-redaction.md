# Brokerage Redaction Policy

## Purpose

TradeGate must prove that brokerage secrets and private account identifiers are redacted before any durable boundary, not only before UI rendering.

Durable boundaries include databases, files, queues, caches, audit logs, analytics events, screenshots, exports, and any persisted test fixture.

## Do Not Store List

Do not commit, upload, persist, log, or cache any of the following:

- Brokerage access tokens
- Brokerage refresh tokens
- Raw brokerage account IDs
- Raw brokerage account numbers
- Robinhood screenshots
- Brokerage screenshots
- Account statements
- Statement-like PDFs
- Raw account exports
- CSV/XLS/XLSX account exports
- Full raw brokerage API payloads
- Unredacted audit events

## Allowed Durable Brokerage Record

Runtime ingestion may persist only the following fields:

- `source_label`
- `connection_id`
- `event_id`
- `account_fingerprint`

`account_fingerprint` must be generated using a keyed digest or stable internal surrogate. Do not use a plain hash of a brokerage account identifier.

## Required Proof

Tests must assert stored records at the persistence layer. A UI-rendered view is not sufficient proof.

Required checks:

1. Repository scanner rejects committed brokerage tokens, account IDs, screenshots, statements, and raw exports.
2. Runtime ingestion stores only the allowed durable record fields.
3. Audit-log tests read the stored log or event record directly.
4. Nested payload regression fixtures prove redaction is value-based, not only key-name-based.
5. Keyed account fingerprints are stable for correlation but not guessable from small identifier search spaces.

## Runtime Rule

All runtime code that handles brokerage data must reduce raw input to a safe durable event before persistence. Raw payloads may be handled only in volatile memory long enough to derive the safe event record and must not cross a durable boundary.
