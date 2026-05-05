import pytest
from agent_routers.schemas.agent import AgentRegistration, InstanceInfo, EndpointSpec


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
                endpoint_id="get_forecast",
                method="POST",
                path="/api/v1/forecast",
                mode="block",
                idempotent=False,
            ),
        ],
    )
    assert reg.agent_id == "weather-agent"
    assert reg.instances[0].weight == 2


def test_agent_registration_rejects_empty_instances():
    with pytest.raises(ValueError):
        AgentRegistration(
            agent_id="bad-agent",
            name="Bad Agent",
            subject="svc-bad",
            instances=[],
            endpoints=[
                EndpointSpec(
                    endpoint_id="e1",
                    method="GET",
                    path="/",
                    mode="block",
                ),
            ],
        )
