-- Agent Routers Database Schema
-- PostgreSQL

CREATE TABLE agents (
    agent_id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    subject VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    base_url VARCHAR(2048) NOT NULL,
    capability VARCHAR(255),
    description TEXT,
    auth_header VARCHAR(255),
    auth_token VARCHAR(2048)
);

CREATE TABLE agent_endpoints (
    agent_id VARCHAR(255) NOT NULL,
    endpoint_type VARCHAR(16) NOT NULL,
    method VARCHAR(16) NOT NULL,
    path VARCHAR(2048) NOT NULL,
    path_params JSONB NOT NULL DEFAULT '[]',
    query_params JSONB NOT NULL DEFAULT '[]',
    body_schema JSONB,
    mode VARCHAR(16) NOT NULL,
    idempotent BOOLEAN NOT NULL DEFAULT FALSE,
    param_mapping JSONB NOT NULL DEFAULT '{}',
    session_config JSONB,
    PRIMARY KEY (agent_id, endpoint_type),
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE,
    CONSTRAINT ck_mode CHECK (mode IN ('block', 'stream'))
);

CREATE TABLE routing_rules (
    rule_id VARCHAR(255) PRIMARY KEY,
    priority INTEGER NOT NULL,
    when_clause JSONB NOT NULL,
    target_agent_id VARCHAR(255),
    target_instance_id VARCHAR(255) NOT NULL,
    target_endpoint_type VARCHAR(16),
    target_capability VARCHAR(255),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
    request_id VARCHAR(255) PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    user_subject VARCHAR(255) NOT NULL,
    agent_id VARCHAR(255),
    instance_id VARCHAR(255),
    method VARCHAR(16),
    status_code INTEGER,
    latency_ms INTEGER,
    request_headers_digest TEXT,
    response_headers_digest TEXT,
    signature TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE request_tracking (
    request_id VARCHAR(255) PRIMARY KEY,
    user_subject VARCHAR(255) NOT NULL,
    agent_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
