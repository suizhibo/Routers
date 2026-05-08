#!/usr/bin/env python3
"""Generate agent registration sequence diagram."""
import subprocess

lines = []
lines.append('<?xml version="1.0" encoding="UTF-8"?>')
lines.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 720" width="960" height="720">')
lines.append('  <style>')
lines.append('    text { font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC", "Microsoft YaHei", sans-serif; }')
lines.append('  </style>')
lines.append('  <defs>')
lines.append('    <marker id="ab" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#2563eb"/></marker>')
lines.append('    <marker id="ad" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#6b7280"/></marker>')
lines.append('  </defs>')
lines.append('  <rect width="960" height="720" fill="#ffffff"/>')
lines.append('  <text x="480" y="32" text-anchor="middle" fill="#111827" font-size="18" font-weight="600">Agent 注册时序图（POST /v1/agents）</text>')

# Participants
parts = [
    (90, 'Agent开发者'),
    (250, 'FastAPI'),
    (390, 'JWTAuth'),
    (540, 'AgentRegistry'),
    (700, 'AgentRepo'),
    (870, 'ClientPool'),
]
box_w, box_h = 120, 36
for x, name in parts:
    lines.append(f'  <rect x="{x-box_w/2}" y="50" width="{box_w}" height="{box_h}" rx="6" fill="#f3f4f6" stroke="#d1d5db" stroke-width="1.5"/>')
    lines.append(f'  <text x="{x}" y="73" text-anchor="middle" fill="#374151" font-size="12" font-weight="600">{name}</text>')
    lines.append(f'  <line x1="{x}" y1="86" x2="{x}" y2="680" stroke="#e5e7eb" stroke-width="1" stroke-dasharray="4,3"/>')

def msg(y, x1, x2, text, color='#2563eb'):
    mid = (x1 + x2) / 2
    lines.append(f'  <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="1.5" marker-end="url(#ab)"/>')
    lines.append(f'  <rect x="{mid-70}" y="{y-14}" width="140" height="16" fill="#ffffff" opacity="0.95"/>')
    lines.append(f'  <text x="{mid}" y="{y-2}" text-anchor="middle" fill="#374151" font-size="10">{text}</text>')

def ret(y, x1, x2, text, color='#6b7280'):
    mid = (x1 + x2) / 2
    lines.append(f'  <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="1.5" stroke-dasharray="4,2" marker-end="url(#ad)"/>')
    lines.append(f'  <rect x="{mid-60}" y="{y-14}" width="120" height="16" fill="#ffffff" opacity="0.95"/>')
    lines.append(f'  <text x="{mid}" y="{y-2}" text-anchor="middle" fill="#374151" font-size="10">{text}</text>')

y = 110
msg(y, 90, 250, 'POST /v1/agents + JWT')
y += 40
msg(y, 250, 390, 'verify_token()')
y += 40
ret(y, 390, 250, 'AuthContext(sub, role)')
y += 40
msg(y, 250, 540, 'registry.register()')
y += 40
msg(y, 540, 700, 'repo.create()')
y += 40
msg(y, 700, 700, 'INSERT agents + endpoints')
y += 40
ret(y, 700, 540, 'Agent model')
y += 40
ret(y, 540, 250, 'AgentRegistrationResponse')
y += 40
msg(y, 250, 870, 'client_pool.create()')
y += 40
ret(y, 870, 250, 'aiohttp ClientSession')
y += 40
ret(y, 250, 90, '201 Created + agent_id')

# Activation boxes
acts = [
    (250, 110, y-110+40),
    (390, 150, 80),
    (540, 230, 160),
    (700, 270, 80),
    (870, 390, 80),
]
for x, y0, h in acts:
    lines.append(f'  <rect x="{x-4}" y="{y0}" width="8" height="{h}" rx="3" fill="#bfdbfe" opacity="0.5"/>')

lines.append('</svg>')

with open('/Users/szb/VibeCoding/Routers/diagrams/register-sequence.svg', 'w') as f:
    f.write('\n'.join(lines))

subprocess.run(['rsvg-convert', '-w', '1920', '/Users/szb/VibeCoding/Routers/diagrams/register-sequence.svg', '-o', '/Users/szb/VibeCoding/Routers/diagrams/register-sequence.png'], check=True)
print('OK: register-sequence.svg + .png')
