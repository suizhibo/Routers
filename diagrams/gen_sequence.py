#!/usr/bin/env python3
"""Generate request forwarding sequence diagram."""
import subprocess

lines = []
lines.append('<?xml version="1.0" encoding="UTF-8"?>')
lines.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 950" width="960" height="950">')
lines.append('  <style>')
lines.append('    text { font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC", "Microsoft YaHei", sans-serif; }')
lines.append('  </style>')
lines.append('  <defs>')
lines.append('    <marker id="ab" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#2563eb"/></marker>')
lines.append('    <marker id="ag" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#16a34a"/></marker>')
lines.append('    <marker id="ad" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#6b7280"/></marker>')
lines.append('  </defs>')
lines.append('  <rect width="960" height="950" fill="#ffffff"/>')
lines.append('  <text x="480" y="32" text-anchor="middle" fill="#111827" font-size="18" font-weight="600">请求转发时序图（POST /v1/route）</text>')

# Participants
parts = [
    (80, 'Client'),
    (220, 'FastAPI'),
    (360, 'JWTAuth'),
    (500, 'Quota'),
    (660, 'Forwarder'),
    (880, 'Agent'),
]
box_w, box_h = 100, 36
for x, name in parts:
    lines.append(f'  <rect x="{x-box_w/2}" y="50" width="{box_w}" height="{box_h}" rx="6" fill="#f3f4f6" stroke="#d1d5db" stroke-width="1.5"/>')
    lines.append(f'  <text x="{x}" y="73" text-anchor="middle" fill="#374151" font-size="12" font-weight="600">{name}</text>')
    # lifeline
    lines.append(f'  <line x1="{x}" y1="86" x2="{x}" y2="900" stroke="#e5e7eb" stroke-width="1" stroke-dasharray="4,3"/>')

# Helper for message arrows
def msg(y, x1, x2, text, color='#2563eb', marker='url(#ab)', dashed=False):
    dash = ' stroke-dasharray="4,2"' if dashed else ''
    mid = (x1 + x2) / 2
    lines.append(f'  <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="1.5" marker-end="{marker}"{dash}/>')
    lines.append(f'  <rect x="{mid-60}" y="{y-14}" width="120" height="16" fill="#ffffff" opacity="0.95"/>')
    lines.append(f'  <text x="{mid}" y="{y-2}" text-anchor="middle" fill="#374151" font-size="10">{text}</text>')

def ret(y, x1, x2, text, color='#6b7280'):
    mid = (x1 + x2) / 2
    lines.append(f'  <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="1.5" stroke-dasharray="4,2" marker-end="url(#ad)"/>')
    lines.append(f'  <rect x="{mid-50}" y="{y-14}" width="100" height="16" fill="#ffffff" opacity="0.95"/>')
    lines.append(f'  <text x="{mid}" y="{y-2}" text-anchor="middle" fill="#374151" font-size="10">{text}</text>')

def self_msg(y, x, text, color='#16a34a'):
    lines.append(f'  <rect x="{x+5}" y="{y-10}" width="110" height="20" rx="4" fill="#f0fdf4" stroke="{color}" stroke-width="1"/>')
    lines.append(f'  <text x="{x+60}" y="{y+4}" text-anchor="middle" fill="#166534" font-size="9">{text}</text>')

# Messages
y = 110
msg(y, 80, 220, 'POST /v1/route')
y += 40
msg(y, 220, 360, 'dispatch (Bearer token)')
y += 40
ret(y, 360, 220, 'set request.state.auth')
y += 40
msg(y, 220, 500, 'dispatch')
y += 40
self_msg(y, 500, 'check Redis quota')
y += 40
ret(y, 500, 220, 'allow / 429')
y += 40
msg(y, 220, 660, 'forward(req, route_req)')
y += 40
msg(y, 660, 660, 'resolve(route_req)', color='#16a34a')
y += 40
self_msg(y, 660, 'SessionManager.get_route()')
y += 40
self_msg(y, 660, 'RuleRepo.list_enabled()')
y += 40
self_msg(y, 660, 'AgentRepo.get_by_id()')
y += 40
ret(y, 660, 660, 'return agent_id', color='#16a34a')
y += 40
msg(y, 660, 880, 'HTTP chat endpoint')
y += 40
ret(y, 880, 660, 'response / SSE chunks')
y += 40
ret(y, 660, 220, 'Response / StreamingResponse')
y += 40
ret(y, 220, 80, 'HTTP response')
y += 40
self_msg(y, 220, 'AuditMiddleware.async write')

# Activation boxes
acts = [
    (220, 110, y-110+40),   # FastAPI active whole time
    (360, 150, 80),         # JWTAuth
    (500, 230, 80),         # Quota
    (660, 310, y-310),      # Forwarder
]
for x, y0, h in acts:
    lines.append(f'  <rect x="{x-4}" y="{y0}" width="8" height="{h}" rx="3" fill="#bfdbfe" opacity="0.5"/>')

lines.append('</svg>')

with open('/Users/szb/VibeCoding/Routers/diagrams/forward-sequence.svg', 'w') as f:
    f.write('\n'.join(lines))

subprocess.run(['rsvg-convert', '/Users/szb/VibeCoding/Routers/diagrams/forward-sequence.svg', '-o', '/dev/null'], check=True)
subprocess.run(['rsvg-convert', '-w', '1920', '/Users/szb/VibeCoding/Routers/diagrams/forward-sequence.svg', '-o', '/Users/szb/VibeCoding/Routers/diagrams/forward-sequence.png'], check=True)
print('OK: forward-sequence.svg + .png')
