#!/usr/bin/env python3
"""Generate request forwarding data flow diagram."""
import subprocess

lines = []
lines.append('<?xml version="1.0" encoding="UTF-8"?>')
lines.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 640" width="960" height="640">')
lines.append('  <style>')
lines.append('    text { font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC", "Microsoft YaHei", sans-serif; }')
lines.append('  </style>')
lines.append('  <defs>')
lines.append('    <marker id="ab" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#2563eb"/></marker>')
lines.append('    <marker id="ag" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#16a34a"/></marker>')
lines.append('  </defs>')
lines.append('  <rect width="960" height="640" fill="#ffffff"/>')
lines.append('  <text x="480" y="32" text-anchor="middle" fill="#111827" font-size="18" font-weight="600">请求转发数据流图</text>')

# Source: RouteRequest
lines.append('  <rect x="60" y="80" width="180" height="140" rx="8" fill="#eff6ff" stroke="#3b82f6" stroke-width="2"/>')
lines.append('  <text x="150" y="105" text-anchor="middle" fill="#1e40af" font-size="13" font-weight="700">RouteRequest</text>')
lines.append('  <text x="150" y="130" text-anchor="middle" fill="#374151" font-size="11">input: "你好"</text>')
lines.append('  <text x="150" y="150" text-anchor="middle" fill="#374151" font-size="11">context.session_id: "s-1"</text>')
lines.append('  <text x="150" y="170" text-anchor="middle" fill="#374151" font-size="11">options.temperature: 0.7</text>')
lines.append('  <text x="150" y="190" text-anchor="middle" fill="#374151" font-size="11">context.user_id: "u-456"</text>')

# Transformer: param_mapping
lines.append('  <rect x="320" y="80" width="200" height="180" rx="8" fill="#fff7ed" stroke="#f97316" stroke-width="2"/>')
lines.append('  <text x="420" y="105" text-anchor="middle" fill="#c2410c" font-size="13" font-weight="700">param_mapping</text>')
lines.append('  <text x="420" y="130" text-anchor="middle" fill="#374151" font-size="11" font-weight="600">path_params</text>')
lines.append('  <text x="420" y="148" text-anchor="middle" fill="#6b7280" font-size="10">session_id → context.session_id</text>')
lines.append('  <text x="420" y="170" text-anchor="middle" fill="#374151" font-size="11" font-weight="600">query_params</text>')
lines.append('  <text x="420" y="188" text-anchor="middle" fill="#6b7280" font-size="10">user_id → context.user_id</text>')
lines.append('  <text x="420" y="210" text-anchor="middle" fill="#374151" font-size="11" font-weight="600">body (dict mapping)</text>')
lines.append('  <text x="420" y="228" text-anchor="middle" fill="#6b7280" font-size="10">message → input</text>')
lines.append('  <text x="420" y="243" text-anchor="middle" fill="#6b7280" font-size="10">metadata → context</text>')
lines.append('  <text x="420" y="258" text-anchor="middle" fill="#6b7280" font-size="10">settings → options</text>')

# Defaults injection
lines.append('  <rect x="320" y="300" width="200" height="80" rx="8" fill="#f0fdf4" stroke="#22c55e" stroke-width="1.5"/>')
lines.append('  <text x="420" y="325" text-anchor="middle" fill="#166534" font-size="12" font-weight="700">body_schema defaults</text>')
lines.append('  <text x="420" y="348" text-anchor="middle" fill="#6b7280" font-size="10">temperature: 0.5 (default)</text>')
lines.append('  <text x="420" y="366" text-anchor="middle" fill="#6b7280" font-size="10">max_tokens: 2048 (default)</text>')

# Output: Upstream Request
lines.append('  <rect x="600" y="80" width="200" height="140" rx="8" fill="#faf5ff" stroke="#9333ea" stroke-width="2"/>')
lines.append('  <text x="700" y="105" text-anchor="middle" fill="#5b21b6" font-size="13" font-weight="700">Upstream Request</text>')
lines.append('  <text x="700" y="130" text-anchor="middle" fill="#374151" font-size="11">POST /chat/s-1?user_id=u-456</text>')
lines.append('  <text x="700" y="155" text-anchor="middle" fill="#374151" font-size="11">Body:</text>')
lines.append('  <text x="700" y="173" text-anchor="middle" fill="#6b7280" font-size="10">message: "你好"</text>')
lines.append('  <text x="700" y="188" text-anchor="middle" fill="#6b7280" font-size="10">metadata: {session_id...}</text>')
lines.append('  <text x="700" y="203" text-anchor="middle" fill="#6b7280" font-size="10">temperature: 0.7</text>')

# Response path
lines.append('  <rect x="600" y="280" width="200" height="100" rx="8" fill="#fef2f2" stroke="#ef4444" stroke-width="1.5"/>')
lines.append('  <text x="700" y="305" text-anchor="middle" fill="#991b1b" font-size="13" font-weight="700">Upstream Response</text>')
lines.append('  <text x="700" y="330" text-anchor="middle" fill="#374151" font-size="11">block: HTTP 200 + body</text>')
lines.append('  <text x="700" y="350" text-anchor="middle" fill="#374151" font-size="11">stream: SSE chunks</text>')
lines.append('  <text x="700" y="370" text-anchor="middle" fill="#374151" font-size="11">session_id extraction</text>')

# Client Response
lines.append('  <rect x="60" y="280" width="180" height="100" rx="8" fill="#f3f4f6" stroke="#6b7280" stroke-width="1.5"/>')
lines.append('  <text x="150" y="305" text-anchor="middle" fill="#374151" font-size="13" font-weight="700">Client Response</text>')
lines.append('  <text x="150" y="330" text-anchor="middle" fill="#374151" font-size="11">透传 status + body</text>')
lines.append('  <text x="150" y="350" text-anchor="middle" fill="#374151" font-size="11">Headers: X-Preferred-Agent</text>')
lines.append('  <text x="150" y="370" text-anchor="middle" fill="#374151" font-size="11">X-Session-Id</text>')

# Arrows: RouteRequest -> param_mapping
lines.append('  <line x1="240" y1="150" x2="320" y2="150" stroke="#2563eb" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('  <rect x="265" y="138" width="30" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="280" y="150" text-anchor="middle" fill="#2563eb" font-size="10">提取</text>')

# param_mapping -> Upstream Request
lines.append('  <line x1="520" y1="170" x2="600" y2="150" stroke="#2563eb" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('  <rect x="545" y="138" width="30" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="560" y="150" text-anchor="middle" fill="#2563eb" font-size="10">构建</text>')

# defaults -> Upstream Request (merge)
lines.append('  <line x1="420" y1="300" x2="420" y2="220" stroke="#16a34a" stroke-width="1.5" marker-end="url(#ag)"/>')
lines.append('  <rect x="425" y="248" width="40" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="445" y="260" text-anchor="middle" fill="#16a34a" font-size="10">合并</text>')

# Upstream Request -> Agent Service (implied, label)
lines.append('  <line x1="800" y1="150" x2="880" y2="150" stroke="#2563eb" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('  <text x="840" y="145" text-anchor="middle" fill="#6b7280" font-size="10">HTTP</text>')

# Agent Service -> Upstream Response
lines.append('  <line x1="880" y1="330" x2="800" y2="330" stroke="#dc2626" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('  <text x="840" y="325" text-anchor="middle" fill="#6b7280" font-size="10">Response</text>')

# Upstream Response -> Client Response
lines.append('  <line x1="600" y1="330" x2="240" y2="330" stroke="#dc2626" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('  <rect x="400" y="318" width="40" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="420" y="330" text-anchor="middle" fill="#dc2626" font-size="10">透传</text>')

# Legend
lines.append('  <g transform="translate(40, 480)">')
lines.append('    <line x1="0" y1="8" x2="25" y2="8" stroke="#2563eb" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('    <text x="32" y="12" fill="#6b7280" font-size="11">请求构建</text>')
lines.append('    <line x1="110" y1="8" x2="135" y2="8" stroke="#16a34a" stroke-width="1.5" marker-end="url(#ag)"/>')
lines.append('    <text x="142" y="12" fill="#6b7280" font-size="11">默认值注入</text>')
lines.append('    <line x1="230" y1="8" x2="255" y2="8" stroke="#dc2626" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('    <text x="262" y="12" fill="#6b7280" font-size="11">响应返回</text>')
lines.append('  </g>')

# Notes
lines.append('  <text x="480" y="540" text-anchor="middle" fill="#6b7280" font-size="11">注: hop-by-hop headers (content-length, transfer-encoding 等) 在转发时被过滤</text>')
lines.append('  <text x="480" y="560" text-anchor="middle" fill="#6b7280" font-size="11">Agent 自定义 auth_header + auth_token 在过滤后附加到上游请求</text>')

lines.append('</svg>')

with open('/Users/szb/VibeCoding/Routers/diagrams/data-flow.svg', 'w') as f:
    f.write('\n'.join(lines))

subprocess.run(['rsvg-convert', '-w', '1920', '/Users/szb/VibeCoding/Routers/diagrams/data-flow.svg', '-o', '/Users/szb/VibeCoding/Routers/diagrams/data-flow.png'], check=True)
print('OK: data-flow.svg + .png')
