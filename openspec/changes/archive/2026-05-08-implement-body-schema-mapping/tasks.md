# Tasks: Implement Body Schema Mapping

## Task 1: Schema Update
- [x] Expand `ParamMapping.body` type from `str | None` to `str | dict[str, str] | None` in `agent_routers/schemas/agent.py`
- [x] Ensure existing string-mode mappings still deserialize correctly
- [x] Add unit test: `ParamMapping` accepts dict body
- [x] Add unit test: `ParamMapping` accepts string body (backward compat)
- [x] Add unit test: `ParamMapping` accepts `None` body

## Task 2: Forwarder Body Building
- [x] Update `Forwarder._build_request()` in `agent_routers/services/forwarder.py`
- [x] Implement dict-mode body mapping: iterate `mapping["body"].items()`, extract each value via `_extract_value`
- [x] Implement schema defaults injection: after building body, fill missing optional fields from `body_schema.properties[].default`
- [x] Keep string mode unchanged for backward compatibility
- [x] Add unit test: `_build_request` with dict body mapping produces correct body_dict
- [x] Add unit test: `_build_request` with dict body + schema defaults injects missing defaults
- [x] Add unit test: `_build_request` with string body still works (backward compat)

## Task 3: Forwarder Integration Tests
- [x] Add test: `forward()` sends correctly mapped body when body is a dict
- [x] Add test: `forward()` with string body still works (backward compat)
- [x] Add test: `_auto_create_session()` with dict body mapping works

## Task 4: Example Update
- [x] Update `examples/agents/knowledge-chat-agent.json`
- [x] Change `chat` endpoint `param_mapping.body` from `"options"` to dict mapping
- [x] Map `input` → `query`, `options.knowledge_base_ids` → `knowledge_base_ids`, etc.
- [x] Verify `body_schema` is consistent with the new mapping

## Task 5: Documentation
- [ ] Update any README or docs that describe `param_mapping.body` usage
