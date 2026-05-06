import pytest
from agent_routers.schemas.agent import AgentRegistration, InstanceInfo, EndpointSpec, ParamMapping, SessionConfig


def test_agent_registration_valid():
    reg = AgentRegistration(
        agent_id="weather-agent",
        name="Weather Agent",
        subject="svc-weather",
        instances=[
            InstanceInfo(instance_id="i1", base_url="https://weather-svc:8080", weight=2),
        ],
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
    assert reg.instances[0].weight == 2
    assert reg.endpoints[0].param_mapping.body is None


def test_agent_registration_rejects_empty_instances():
    with pytest.raises(ValueError):
        AgentRegistration(
            agent_id="bad-agent",
            name="Bad Agent",
            subject="svc-bad",
            instances=[],
            endpoints=[
                EndpointSpec(
                    endpoint_type="chat",
                    method="GET",
                    path="/",
                    mode="block",
                ),
            ],
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
