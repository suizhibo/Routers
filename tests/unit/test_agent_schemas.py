import pytest
from agent_routers.schemas.agent import AgentRegistration, EndpointSpec, ParamMapping, SessionConfig


def test_agent_registration_valid():
    reg = AgentRegistration(
        agent_id="weather-agent",
        name="Weather Agent",
        subject="svc-weather",
        base_url="https://weather-svc:8080",
        capability="weather",
        description="Provides weather forecasts",
        endpoints=[
            EndpointSpec(
                endpoint_type="chat",
                method="POST",
                path="/api/v1/forecast",
                mode="block",
                idempotent=False,
                param_mapping=ParamMapping(path_params={}, query_params={}, body=None),
                session_config=None,
            ),
        ],
    )
    assert reg.agent_id == "weather-agent"
    assert reg.base_url == "https://weather-svc:8080"
    assert reg.capability == "weather"
    assert reg.description == "Provides weather forecasts"
    assert reg.endpoints[0].param_mapping.body is None


def test_agent_registration_rejects_empty_endpoints():
    with pytest.raises(ValueError):
        AgentRegistration(
            agent_id="bad-agent",
            name="Bad Agent",
            subject="svc-bad",
            base_url="http://localhost:8001",
            endpoints=[],
        )


def test_endpoint_spec_with_session_config():
    ep = EndpointSpec(
        endpoint_type="chat",
        method="POST",
        path="/api/chat/{session_id}",
        mode="stream",
        param_mapping=ParamMapping(
            path_params={"session_id": "context.session_id"},
            body="input",
        ),
        session_config=SessionConfig(response_header="X-Session-ID"),
    )
    assert ep.session_config.response_header == "X-Session-ID"
    assert ep.param_mapping.path_params["session_id"] == "context.session_id"


def test_agent_registration_optional_fields():
    reg = AgentRegistration(
        agent_id="minimal-agent",
        name="Minimal Agent",
        subject="svc-minimal",
        base_url="http://localhost:8001",
        endpoints=[
            EndpointSpec(
                endpoint_type="chat",
                method="GET",
                path="/",
                mode="block",
                idempotent=False,
            ),
        ],
    )
    assert reg.capability is None
    assert reg.description is None
    assert reg.auth_header is None
    assert reg.auth_token is None


def test_agent_registration_with_auth_fields():
    reg = AgentRegistration(
        agent_id="kb-agent",
        name="KB Agent",
        subject="svc-kb",
        base_url="https://kb:8080",
        auth_header="x-api-key",
        auth_token="secret-123",
        endpoints=[
            EndpointSpec(
                endpoint_type="chat",
                method="POST",
                path="/api/chat",
                mode="block",
                idempotent=False,
                param_mapping=ParamMapping(path_params={}, query_params={}, body=None),
                session_config=None,
            ),
        ],
    )
    assert reg.auth_header == "x-api-key"
    assert reg.auth_token == "secret-123"


def test_param_mapping_dict_body():
    pm = ParamMapping(
        path_params={"session_id": "context.session_id"},
        body={"query": "input", "kb_ids": "options.knowledge_base_ids"},
    )
    assert pm.body == {"query": "input", "kb_ids": "options.knowledge_base_ids"}


def test_param_mapping_string_body():
    pm = ParamMapping(body="options")
    assert pm.body == "options"


def test_param_mapping_none_body():
    pm = ParamMapping()
    assert pm.body is None
