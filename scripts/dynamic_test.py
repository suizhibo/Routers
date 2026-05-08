"""Dynamic API tests against a running AgentRouters service."""
from __future__ import annotations

import asyncio
import jwt
import time
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"
JWKS_URL = "http://localhost:8080/.well-known/jwks.json"

# Load the private key from the JWKS server script
PRIVATE_PEM = Path("/tmp/mock_jwks_private.pem").read_text()


def make_token(sub: str = "test-user", role: str = "user", exp_offset: int = 3600) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "role": role,
            "iss": "http://test-issuer",
            "aud": "agent-routers",
            "iat": now,
            "exp": now + exp_offset,
        },
        PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": "test-key-1"},
    )


@dataclass
class TestResult:
    name: str
    status: str  # PASS / FAIL / SKIP
    detail: str = ""


results: list[TestResult] = []


def record(name: str, status: str, detail: str = ""):
    results.append(TestResult(name, status, detail))
    icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⏭️"
    print(f"  {icon} {name}: {status} {detail}")


async def run_tests():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        # ── Health / Public ──────────────────────────────────────────────
        print("\n--- Public Endpoints ---")
        r = await client.get("/health")
        record("GET /health", "PASS" if r.status_code == 200 else "FAIL", f"status={r.status_code}")

        r = await client.get("/readiness")
        record("GET /readiness", "PASS" if r.status_code == 200 else "FAIL", f"status={r.status_code}")

        # ── Auth required ────────────────────────────────────────────────
        print("\n--- Auth Required ---")
        r = await client.get("/v1/agents")
        record("GET /v1/agents no auth", "PASS" if r.status_code == 401 else "FAIL", f"status={r.status_code}")

        user_token = make_token(sub="test-user", role="user")
        admin_token = make_token(sub="test-admin", role="admin")
        agent_token = make_token(sub="test-subject", role="user")

        # ── Agents CRUD ──────────────────────────────────────────────────
        print("\n--- Agents CRUD ---")
        agent_payload = {
            "agent_id": "test-agent-1",
            "name": "Test Agent",
            "subject": "test-subject",
            "base_url": "http://agent-backend:9001",
            "endpoints": [
                {
                    "endpoint_id": "create_session",
                    "operation_types": ["create_session"],
                    "method": "POST",
                    "path": "/api/session",
                    "mode": "block",
                    "param_mapping": {"body": "input"},
                    "session_config": {"response_header": "x-session-id"}
                },
                {
                    "endpoint_id": "chat",
                    "operation_types": ["chat"],
                    "method": "POST",
                    "path": "/api/chat/{session_id}",
                    "mode": "stream",
                    "param_mapping": {
                        "path_params": {"session_id": "context.session_id"},
                        "body": "input"
                    }
                },
                {
                    "endpoint_id": "terminate_session",
                    "operation_types": ["terminate_session"],
                    "method": "DELETE",
                    "path": "/api/session/{session_id}",
                    "mode": "block",
                    "param_mapping": {
                        "path_params": {"session_id": "context.session_id"}
                    }
                }
            ]
        }

        r = await client.post("/v1/agents", json=agent_payload, headers={"Authorization": f"Bearer {agent_token}"})
        record("POST /v1/agents register", "PASS" if r.status_code == 201 else "FAIL", f"status={r.status_code}")
        if r.status_code != 201:
            print(f"    body: {r.text[:500]}")

        r = await client.get("/v1/agents", headers={"Authorization": f"Bearer {user_token}"})
        record("GET /v1/agents list", "PASS" if r.status_code == 200 else "FAIL", f"status={r.status_code}")

        r = await client.get("/v1/agents/test-agent-1", headers={"Authorization": f"Bearer {user_token}"})
        record("GET /v1/agents/{id} detail", "PASS" if r.status_code == 200 else "FAIL", f"status={r.status_code}")

        # ── Rules CRUD (admin only) ──────────────────────────────────────
        print("\n--- Rules CRUD ---")
        rule_payload = {
            "rule_id": "rule-1",
            "priority": 10,
            "when_clause": {"header.region": "us-east"},
            "target_agent_id": "test-agent-1",
            "target_endpoint_type": "chat",
            "enabled": True,
        }

        r = await client.post("/v1/rules", json=rule_payload, headers={"Authorization": f"Bearer {admin_token}"})
        record("POST /v1/rules create", "PASS" if r.status_code == 201 else "FAIL", f"status={r.status_code}")
        if r.status_code != 201:
            print(f"    body: {r.text[:500]}")

        r = await client.get("/v1/rules", headers={"Authorization": f"Bearer {admin_token}"})
        record("GET /v1/rules list", "PASS" if r.status_code == 200 else "FAIL", f"status={r.status_code}")

        r = await client.get("/v1/rules/rule-1", headers={"Authorization": f"Bearer {admin_token}"})
        record("GET /v1/rules/{id} detail", "PASS" if r.status_code == 200 else "FAIL", f"status={r.status_code}")

        # non-admin should be 403
        r = await client.get("/v1/rules", headers={"Authorization": f"Bearer {user_token}"})
        record("GET /v1/rules non-admin", "PASS" if r.status_code == 403 else "FAIL", f"status={r.status_code}")

        # ── Route Forwarding (POST /v1/route, no path params) ────────────
        print("\n--- Route Forwarding (v2) ---")

        # 1. No auth should 401
        route_payload = {"input": "hello", "context": {"operation": "chat"}, "options": {}}
        r = await client.post("/v1/route", json=route_payload)
        record("POST /v1/route no auth", "PASS" if r.status_code == 401 else "FAIL", f"status={r.status_code}")

        # 2. L4: Operation match (context.operation -> endpoint)
        # Since there's no real agent backend, expect 502/504 (unreachable)
        r = await client.post("/v1/route", json=route_payload, headers={"Authorization": f"Bearer {user_token}"})
        record(
            "POST /v1/route L4 operation match",
            "PASS" if r.status_code in (200, 502, 504) else "FAIL",
            f"status={r.status_code}",
        )
        if r.status_code not in (200, 502, 504):
            print(f"    body: {r.text[:500]}")

        # 3. L1: Preferred header overrides
        r = await client.post(
            "/v1/route",
            json=route_payload,
            headers={
                "Authorization": f"Bearer {user_token}",
                "X-Preferred-Agent": "test-agent-1",
                "X-Preferred-Endpoint": "chat",
            },
        )
        record(
            "POST /v1/route L1 preferred header",
            "PASS" if r.status_code in (200, 502, 504) else "FAIL",
            f"status={r.status_code}",
        )

        # 4. L3: Rule match (header.region = us-east)
        r = await client.post(
            "/v1/route",
            json=route_payload,
            headers={
                "Authorization": f"Bearer {user_token}",
                "region": "us-east",
            },
        )
        record(
            "POST /v1/route L3 rule match",
            "PASS" if r.status_code in (200, 502, 504) else "FAIL",
            f"status={r.status_code}",
        )

        # 5. L2: Session sticky (first request gets session_id, second uses it)
        # We simulate by setting a session config that would return a session_id
        # Since backend is down, we can't test full flow, but we test cache miss -> operation match
        r = await client.post(
            "/v1/route",
            json={"input": "create", "context": {"operation": "create_session"}, "options": {}},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        record(
            "POST /v1/route L4 create_session",
            "PASS" if r.status_code in (200, 502, 504) else "FAIL",
            f"status={r.status_code}",
        )

        # 6. Unknown operation should 404
        r = await client.post(
            "/v1/route",
            json={"input": "???", "context": {"operation": "nonexistent"}, "options": {}},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        record(
            "POST /v1/route unknown operation",
            "PASS" if r.status_code == 404 else "FAIL",
            f"status={r.status_code}",
        )

        # ── Audit ────────────────────────────────────────────────────────
        print("\n--- Audit ---")
        r = await client.get("/v1/audit/fake-request-id", headers={"Authorization": f"Bearer {admin_token}"})
        record("GET /v1/audit/{request_id}", "PASS" if r.status_code in (200, 404) else "FAIL", f"status={r.status_code}")

        # ── Cancel ───────────────────────────────────────────────────────
        print("\n--- Cancel ---")
        r = await client.post("/v1/requests/unknown-request/cancel", headers={"Authorization": f"Bearer {user_token}"})
        record("POST /v1/requests/{id}/cancel", "PASS" if r.status_code in (200, 404) else "FAIL", f"status={r.status_code}")

        # ── Cleanup ──────────────────────────────────────────────────────
        print("\n--- Cleanup ---")
        r = await client.delete("/v1/agents/test-agent-1", headers={"Authorization": f"Bearer {agent_token}"})
        record("DELETE /v1/agents/{id}", "PASS" if r.status_code == 204 else "FAIL", f"status={r.status_code}")

        r = await client.delete("/v1/rules/rule-1", headers={"Authorization": f"Bearer {admin_token}"})
        record("DELETE /v1/rules/{id}", "PASS" if r.status_code == 204 else "FAIL", f"status={r.status_code}")

    # ── Summary ────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped  ({len(results)} total)")
    if failed:
        print("\nFailed tests:")
        for r in results:
            if r.status == "FAIL":
                print(f"  - {r.name}: {r.detail}")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(run_tests())
    sys.exit(0 if ok else 1)
