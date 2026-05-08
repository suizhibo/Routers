#!/usr/bin/env python3
"""Generate AgentRouters system architecture diagram."""
import subprocess
import sys

lines = []
lines.append('<?xml version="1.0" encoding="UTF-8"?>')
lines.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 780" width="960" height="780">')
lines.append('  <style>')
lines.append('    text { font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC", "Microsoft YaHei", sans-serif; }')
lines.append('  </style>')
lines.append('  <defs>')
lines.append('    <marker id="ab" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#2563eb"/></marker>')
lines.append('    <marker id="ag" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#16a34a"/></marker>')
lines.append('    <marker id="ao" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#ea580c"/></marker>')
lines.append('    <marker id="ap" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#9333ea"/></marker>')
lines.append('  </defs>')
lines.append('  <rect width="960" height="780" fill="#ffffff"/>')
lines.append('  <text x="480" y="32" text-anchor="middle" fill="#111827" font-size="18" font-weight="600">AgentRouters 系统架构图</text>')

# Layer containers
layers = [
    (50, 70, '#f9fafb', '#d1d5db', '外部系统'),
    (140, 80, '#eff6ff', '#bfdbfe', 'API 层 (FastAPI)'),
    (240, 70, '#fff7ed', '#fed7aa', '中间件 (横切关注点)'),
    (340, 90, '#f0fdf4', '#bbf7d0', '业务逻辑层 (Services)'),
    (450, 90, '#faf5ff', '#e9d5ff', '适配器层 (Adapters)'),
    (560, 80, '#f0fdfa', '#99f6e4', '存储与外部服务'),
]
for y, h, fill, stroke, label in layers:
    lines.append(f'  <rect x="40" y="{y}" width="880" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1" stroke-dasharray="6,4"/>')
    lines.append(f'  <text x="55" y="{y+18}" fill="#6b7280" font-size="10" font-weight="600" letter-spacing="0.06em">{label}</text>')

# External nodes
# Client browser
lines.append('  <rect x="100" y="72" width="120" height="40" rx="6" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>')
lines.append('  <rect x="100" y="72" width="120" height="18" rx="6" fill="#374151" stroke="none"/>')
lines.append('  <rect x="100" y="84" width="120" height="6" fill="#374151" stroke="none"/>')
lines.append('  <circle cx="112" cy="81" r="3" fill="#ef4444" opacity="0.8"/>')
lines.append('  <circle cx="124" cy="81" r="3" fill="#f59e0b" opacity="0.8"/>')
lines.append('  <circle cx="136" cy="81" r="3" fill="#10b981" opacity="0.8"/>')
lines.append('  <text x="160" y="105" text-anchor="middle" fill="#374151" font-size="12" font-weight="600">Client</text>')

# Agent Service
lines.append('  <rect x="740" y="72" width="140" height="40" rx="8" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>')
lines.append('  <text x="810" y="98" text-anchor="middle" fill="#111827" font-size="12" font-weight="600">Agent Service</text>')

# JWKS Server
lines.append('  <rect x="420" y="72" width="120" height="40" rx="8" fill="#ffffff" stroke="#d1d5db" stroke-width="1.5"/>')
lines.append('  <text x="480" y="98" text-anchor="middle" fill="#111827" font-size="12" font-weight="600">JWKS Server</text>')

# API nodes
api_nodes = [(80, '/health'), (200, '/v1/agents'), (330, '/v1/route'), (460, '/v1/rules'), (590, '/v1/audit'), (720, '/v1/requests')]
for x, label in api_nodes:
    lines.append(f'  <rect x="{x}" y="168" width="105" height="36" rx="6" fill="#ffffff" stroke="#bfdbfe" stroke-width="1.5"/>')
    lines.append(f'  <text x="{x+52}" y="190" text-anchor="middle" fill="#2563eb" font-size="11" font-weight="600">{label}</text>')

# Middleware nodes
mw_nodes = [(130, 'RequestId'), (330, 'JWTAuth'), (530, 'Quota'), (730, 'Audit')]
for x, label in mw_nodes:
    lines.append(f'  <rect x="{x}" y="262" width="130" height="36" rx="6" fill="#fff7ed" stroke="#fdba74" stroke-width="1.5"/>')
    lines.append(f'  <text x="{x+65}" y="285" text-anchor="middle" fill="#c2410c" font-size="12" font-weight="600">{label}</text>')

# Services nodes
svcs = [(70, 'Forwarder', True), (230, 'RoutingEngine', False), (400, 'Registry', False), (550, 'SessionManager', False), (730, 'Coordination', False)]
for x, label, accent in svcs:
    stroke = '#22c55e' if accent else '#86efac'
    fill = '#dcfce7' if accent else '#f0fdf4'
    weight = '700' if accent else '600'
    lines.append(f'  <rect x="{x}" y="372" width="130" height="40" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="{2 if accent else 1.5}"/>')
    lines.append(f'  <text x="{x+65}" y="398" text-anchor="middle" fill="#166534" font-size="12" font-weight="{weight}">{label}</text>')

# Adapters nodes
adapters = [(60, 'AgentRepo'), (190, 'RuleRepo'), (320, 'AuditRepo'), (450, 'HTTPClient'), (590, 'JWKS'), (710, 'RedisQuota')]
for x, label in adapters:
    lines.append(f'  <rect x="{x}" y="482" width="110" height="40" rx="8" fill="#ede9fe" stroke="#c4b5fd" stroke-width="1.5"/>')
    lines.append(f'  <text x="{x+55}" y="508" text-anchor="middle" fill="#5b21b6" font-size="12" font-weight="600">{label}</text>')

# Storage: PostgreSQL cylinder
lines.append('  <ellipse cx="260" cy="590" rx="60" ry="14" fill="#dbeafe" stroke="#60a5fa" stroke-width="1.5"/>')
lines.append('  <rect x="200" y="590" width="120" height="40" fill="#dbeafe" stroke="none"/>')
lines.append('  <line x1="200" y1="590" x2="200" y2="630" stroke="#60a5fa" stroke-width="1.5"/>')
lines.append('  <line x1="320" y1="590" x2="320" y2="630" stroke="#60a5fa" stroke-width="1.5"/>')
lines.append('  <ellipse cx="260" cy="630" rx="60" ry="14" fill="#93c5fd" stroke="#60a5fa" stroke-width="1.5"/>')
lines.append('  <text x="260" y="616" text-anchor="middle" fill="#1e3a8a" font-size="11" font-weight="600">PostgreSQL</text>')

# Redis
lines.append('  <rect x="460" y="590" width="100" height="40" rx="8" fill="#fee2e2" stroke="#fca5a5" stroke-width="1.5"/>')
lines.append('  <text x="510" y="616" text-anchor="middle" fill="#991b1b" font-size="12" font-weight="600">Redis</text>')

# === Arrows ===
# Client -> /v1/route
lines.append('  <line x1="160" y1="112" x2="382" y2="168" stroke="#2563eb" stroke-width="1.5" marker-end="url(#ab)"/>')
# /v1/route -> Forwarder (route around left)
lines.append('  <path d="M 382 204 L 382 240 L 60 240 L 60 340 L 70 340 L 70 372" stroke="#2563eb" stroke-width="1.5" fill="none" marker-end="url(#ab)"/>')
# Forwarder -> RoutingEngine
lines.append('  <line x1="200" y1="392" x2="230" y2="392" stroke="#2563eb" stroke-width="1.5" marker-end="url(#ab)"/>')
# Forwarder -> HTTPClient
lines.append('  <path d="M 135 412 L 135 450 L 505 450 L 505 482" stroke="#2563eb" stroke-width="1.5" fill="none" marker-end="url(#ab)"/>')
# HTTPClient -> Agent Service (around right)
lines.append('  <path d="M 560 522 L 560 560 L 900 560 L 900 112" stroke="#2563eb" stroke-width="1.5" fill="none" marker-end="url(#ab)"/>')
# RoutingEngine -> SessionManager
lines.append('  <line x1="360" y1="392" x2="550" y2="392" stroke="#16a34a" stroke-width="1.5" marker-end="url(#ag)"/>')
# SessionManager -> Redis
lines.append('  <path d="M 615 412 L 615 450 L 510 450 L 510 560 L 510 590" stroke="#16a34a" stroke-width="1.5" fill="none" marker-end="url(#ag)"/>')
# RoutingEngine -> RuleRepo
lines.append('  <path d="M 295 412 L 295 450 L 240 450 L 240 482" stroke="#16a34a" stroke-width="1.5" fill="none" marker-end="url(#ag)"/>')
# Registry -> AgentRepo
lines.append('  <path d="M 465 412 L 465 450 L 110 450 L 110 482" stroke="#16a34a" stroke-width="1.5" fill="none" marker-end="url(#ag)"/>')
# AgentRepo -> PostgreSQL
lines.append('  <path d="M 110 522 L 110 560 L 200 560 L 200 590" stroke="#16a34a" stroke-width="1.5" fill="none" marker-end="url(#ag)"/>')
# RuleRepo -> PostgreSQL
lines.append('  <path d="M 240 522 L 240 560 L 260 560 L 260 590" stroke="#16a34a" stroke-width="1.5" fill="none" marker-end="url(#ag)"/>')
# AuditRepo -> PostgreSQL
lines.append('  <path d="M 370 522 L 370 560 L 320 560 L 320 590" stroke="#16a34a" stroke-width="1.5" fill="none" marker-end="url(#ag)"/>')
# JWTAuth -> JWKS Server
lines.append('  <path d="M 395 298 L 395 340 L 480 340 L 480 112" stroke="#9333ea" stroke-width="1.5" fill="none" marker-end="url(#ap)"/>')
# Quota -> Redis
lines.append('  <path d="M 595 298 L 595 340 L 620 340 L 620 450 L 620 560 L 560 560 L 560 590" stroke="#9333ea" stroke-width="1.5" fill="none" marker-end="url(#ap)"/>')
# AuditMiddleware -> AuditRepo
lines.append('  <path d="M 795 298 L 795 340 L 370 340 L 370 450 L 370 482" stroke="#ea580c" stroke-width="1.5" fill="none" marker-end="url(#ao)"/>')
# Middleware order flow
lines.append('  <line x1="260" y1="280" x2="330" y2="280" stroke="#fdba74" stroke-width="1.5" marker-end="url(#ao)"/>')
lines.append('  <line x1="460" y1="280" x2="530" y2="280" stroke="#fdba74" stroke-width="1.5" marker-end="url(#ao)"/>')
lines.append('  <line x1="660" y1="280" x2="730" y2="280" stroke="#fdba74" stroke-width="1.5" marker-end="url(#ao)"/>')

# Legend
lines.append('  <g transform="translate(40, 690)">')
lines.append('    <line x1="0" y1="8" x2="25" y2="8" stroke="#2563eb" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('    <text x="32" y="12" fill="#6b7280" font-size="11">主请求流</text>')
lines.append('    <line x1="110" y1="8" x2="135" y2="8" stroke="#16a34a" stroke-width="1.5" marker-end="url(#ag)"/>')
lines.append('    <text x="142" y="12" fill="#6b7280" font-size="11">数据查询流</text>')
lines.append('    <line x1="230" y1="8" x2="255" y2="8" stroke="#ea580c" stroke-width="1.5" marker-end="url(#ao)"/>')
lines.append('    <text x="262" y="12" fill="#6b7280" font-size="11">审计流</text>')
lines.append('    <line x1="320" y1="8" x2="345" y2="8" stroke="#9333ea" stroke-width="1.5" marker-end="url(#ap)"/>')
lines.append('    <text x="352" y="12" fill="#6b7280" font-size="11">认证/限流</text>')
lines.append('  </g>')

lines.append('</svg>')

with open('/Users/szb/VibeCoding/Routers/diagrams/architecture-diagram.svg', 'w') as f:
    f.write('\n'.join(lines))

# Validate and export
subprocess.run(['rsvg-convert', '/Users/szb/VibeCoding/Routers/diagrams/architecture-diagram.svg', '-o', '/dev/null'], check=True)
subprocess.run(['rsvg-convert', '-w', '1920', '/Users/szb/VibeCoding/Routers/diagrams/architecture-diagram.svg', '-o', '/Users/szb/VibeCoding/Routers/diagrams/architecture-diagram.png'], check=True)
print('OK: architecture-diagram.svg + .png')
