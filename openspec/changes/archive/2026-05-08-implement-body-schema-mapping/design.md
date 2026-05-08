# Design: Body Schema Mapping

## Data Model

No database changes. `AgentEndpoint.body_schema` and `AgentEndpoint.param_mapping` already exist as JSON columns. The change is purely in how `param_mapping` is interpreted.

### ParamMapping Schema Update

```python
class ParamMapping(BaseModel):
    path_params: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | dict[str, str] | None = None  # <-- expanded type
```

## Body Building Logic

### String mode (existing)
```python
body_dict = _extract_value(req_dict, mapping["body"])  # e.g., "options" → entire dict
```

### Dict mode (new)
```python
body_dict = {}
for target_key, source_path in mapping["body"].items():
    val = _extract_value(req_dict, source_path)
    if val is not None:
        body_dict[target_key] = val
```

### Schema defaults injection
After building `body_dict`, if `endpoint.body_schema` is present:
```python
if endpoint.body_schema and endpoint.body_schema.get("type") == "object":
    for prop_name, prop_schema in endpoint.body_schema.get("properties", {}).items():
        if prop_name not in body_dict and "default" in prop_schema:
            body_dict[prop_name] = prop_schema["default"]
```

## Forwarder Integration

In `Forwarder._build_request()` (`forwarder.py`):

```python
body_dict = None
if endpoint.method not in IDEMPOTENT_METHODS and mapping.get("body"):
    body_cfg = mapping["body"]
    if isinstance(body_cfg, dict):
        body_dict = {}
        for target_key, source_path in body_cfg.items():
            val = _extract_value(req_dict, source_path)
            if val is not None:
                body_dict[target_key] = val
        # Inject defaults from body_schema
        if endpoint.body_schema and endpoint.body_schema.get("type") == "object":
            for prop_name, prop_schema in endpoint.body_schema.get("properties", {}).items():
                if prop_name not in body_dict and "default" in prop_schema:
                    body_dict[prop_name] = prop_schema["default"]
    else:
        body_dict = _extract_value(req_dict, body_cfg)
```

## Example Mapping

For the knowledge-chat-agent's `chat` endpoint:
```json
{
  "param_mapping": {
    "path_params": {"session_id": "context.session_id"},
    "query_params": {},
    "body": {
      "query": "input",
      "knowledge_base_ids": "options.knowledge_base_ids",
      "agent_id": "options.agent_id"
    }
  },
  "body_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "knowledge_base_ids": {"type": "array", "items": {"type": "string"}},
      "agent_id": {"type": "string"},
      "disable_title": {"type": "boolean", "default": false}
    },
    "required": ["query"]
  }
}
```

With `RouteRequest(input="hello", context={"session_id": "abc"}, options={"knowledge_base_ids": ["kb1"]})`, the upstream body becomes:
```json
{"query": "hello", "knowledge_base_ids": ["kb1"], "disable_title": false}
```

## Files to Change

| File | Change |
|------|--------|
| `agent_routers/schemas/agent.py` | Expand `ParamMapping.body` type to `str \| dict[str, str] \| None` |
| `agent_routers/services/forwarder.py` | Update `_build_request()` to handle dict-mode body mapping + schema defaults |
| `tests/unit/test_param_mapping.py` | Add tests for dict-mode body extraction and schema defaults |
| `tests/unit/test_forwarder.py` | Add test: forward with dict body mapping builds correct upstream body |
| `examples/agents/knowledge-chat-agent.json` | Update chat endpoint `param_mapping.body` to use new dict format |
