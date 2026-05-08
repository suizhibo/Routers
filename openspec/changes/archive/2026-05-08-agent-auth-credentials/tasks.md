# Tasks: Agent Authentication Credentials

## Task 1: Model and Schema Updates
- [ ] Add `auth_header` (String 255) and `auth_token` (String 2048) to `Agent` SQLAlchemy model
- [ ] Add fields to `AgentRegistration`, `AgentDetail`, `AgentListItem` Pydantic schemas
- [ ] `AgentDetail` should mask `auth_token` as `"***"` (handle in registry service, not schema)
- [ ] `AgentListItem` omits `auth_token`
- [ ] Update `schema.sql`

## Task 2: Repository and Service Updates
- [ ] `AgentRepository.create()` persists `auth_header` and `auth_token`
- [ ] `AgentRegistry.get_agent()` masks `auth_token` in response
- [ ] `AgentRegistry.list_agents()` omits `auth_token` from list items

## Task 3: Forwarder Integration
- [ ] `Forwarder.forward()` — inject `auth_header: auth_token` into upstream request headers
- [ ] `Forwarder._auto_create_session()` — same injection for create-session calls
- [ ] Agent header overrides downstream header with same name

## Task 4: Database Migration
- [ ] Generate Alembic migration adding `auth_header` and `auth_token` to `agents` table
- [ ] Run migration against local DB

## Task 5: Tests
- [ ] Unit test: `AgentRegistration` accepts optional auth fields
- [ ] Unit test: Forwarder injects auth header when agent has credentials
- [ ] Unit test: Forwarder does not inject when credentials absent
- [ ] Unit test: Forwarder agent header overrides downstream header
- [ ] Integration test: Register agent with auth, verify detail masks token
- [ ] Integration test: List agents does not expose token

## Task 6: Example Update
- [ ] Update `examples/agents/intelligent-kb-agent.json` with `auth_header` and `auth_token`
