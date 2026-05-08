# Proposal: Implement Body Schema Mapping

## Problem

Currently, `param_mapping.body` only supports a single dot-path string (e.g., `"options"`, `"input"`, `"$"`). This extracts an entire field from `RouteRequest` and sends it as the upstream request body. This is too coarse for upstream APIs that expect a specific body structure.

For example, the knowledge-base chat agent's `chat` endpoint expects:
```json
{
  "query": "...",
  "knowledge_base_ids": ["..."],
  "agent_id": "..."
}
```

With the current system, callers must pack all these fields into `RouteRequest.options` and set `body: "options"`. There's no way to map `RouteRequest.input` → `body.query` and `RouteRequest.options.knowledge_base_ids` → `body.knowledge_base_ids` independently.

## Scope

### In Scope
1. Extend `param_mapping.body` to support both:
   - **String** (backward-compatible): `"input"`, `"options"`, `"$"`, `"context.session_id"`
   - **Dict** (new): `{"query": "input", "knowledge_base_ids": "options.knowledge_base_ids"}`
2. When `body` is a dict, build the request body by mapping each key using dot-path extraction
3. Use `body_schema` (if present) for:
   - Default value injection for missing optional fields
   - Type coercion / basic validation
4. Update `Forwarder._build_request()` to handle the new mapping format
5. Update Pydantic schemas (`ParamMapping`) to accept `body: str | dict | None`
6. Update tests and examples

### Out of Scope
- Full JSON Schema validation (just defaults and basic type hints)
- Nested object mapping beyond one level in the target body
- Transformations (formatting, type conversion beyond simple coercion)
- Removing the existing string-based body mapping

## Design Decisions

### Dual-mode body mapping
Keep string mode for backward compatibility. Add dict mode for granular control. The forwarder checks `isinstance(mapping.body, dict)` to decide which path to take.

### Schema-guided defaults
If `body_schema` defines a property with a `default`, and the mapping doesn't provide a value for that key, inject the default. This reduces the need for callers to specify every optional field.

### Dot-path source, flat target
The dict mode maps flat target keys to dot-path sources: `{"target_key": "source.dot.path"}`. The resulting body is a flat object. This keeps the mapping syntax simple and covers the common case.
