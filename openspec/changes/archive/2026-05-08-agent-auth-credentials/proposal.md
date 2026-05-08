# Proposal: Agent Authentication Credentials

## Problem
Each upstream agent may require its own authentication credentials. Currently, the Forwarder passes downstream request headers directly to upstream agents, with no way to inject per-agent auth tokens. For example, the knowledge-base agent requires `x-api-key` in headers.

## Scope

### In Scope
1. Add `auth_header` (header name) and `auth_token` (header value) to Agent model/schemas
2. Update Forwarder to inject agent auth headers into upstream requests
3. Mask auth_token in `AgentDetail` / `AgentListItem` responses (security)
4. Database migration
5. Update tests

### Out of Scope
- OAuth / JWT flows (header-based static tokens only)
- Credential encryption at rest (can be added later)
- Query-param or body-based auth

## Design Decisions

### Simple header-based approach
Store `auth_header` (e.g. "x-api-key") and `auth_token` (e.g. "secret-123") as nullable VARCHAR fields. This covers the immediate need without over-engineering.

### Agent token overrides downstream headers
If both downstream and agent define the same header name, the agent's token wins. This prevents downstream clients from spoofing upstream auth.

### Response masking
`AgentDetail` and `AgentListItem` return `auth_header` but mask `auth_token` as `"***"` (or omit it). Only the registration API accepts the raw token.
