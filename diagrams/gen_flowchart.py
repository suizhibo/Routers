#!/usr/bin/env python3
"""Generate L1-L4 routing decision flowchart."""
import subprocess

lines = []
lines.append('<?xml version="1.0" encoding="UTF-8"?>')
lines.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 720" width="960" height="720">')
lines.append('  <style>')
lines.append('    text { font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC", "Microsoft YaHei", sans-serif; }')
lines.append('  </style>')
lines.append('  <defs>')
lines.append('    <marker id="ab" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#2563eb"/></marker>')
lines.append('    <marker id="ar" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#dc2626"/></marker>')
lines.append('  </defs>')
lines.append('  <rect width="960" height="720" fill="#ffffff"/>')
lines.append('  <text x="480" y="32" text-anchor="middle" fill="#111827" font-size="18" font-weight="600">AgentRouters L1-L4 路由决策流程</text>')

# Level labels on left
levels = [
    (110, 'L1 优先路由'),
    (230, 'L2 会话缓存'),
    (350, 'L3 规则匹配'),
    (470, 'L4 默认兜底'),
]
for y, label in levels:
    lines.append(f'  <text x="50" y="{y}" fill="#6b7280" font-size="11" font-weight="600">{label}</text>')

# Start
lines.append('  <rect x="240" y="50" width="120" height="40" rx="20" fill="#f3f4f6" stroke="#6b7280" stroke-width="1.5"/>')
lines.append('  <text x="300" y="75" text-anchor="middle" fill="#374151" font-size="13" font-weight="600">Start</text>')

# Diamonds
diamonds = [
    (300, 150, 130, 40, 'X-Preferred-Agent?'),
    (300, 270, 120, 40, 'Session Cache?'),
    (300, 390, 120, 40, 'Match Rule?'),
    (300, 510, 120, 40, 'Default Agent?'),
]
for cx, cy, hw, hh, label in diamonds:
    pts = f'{cx},{cy-hh} {cx+hw},{cy} {cx},{cy+hh} {cx-hw},{cy}'
    lines.append(f'  <polygon points="{pts}" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.5"/>')
    # Split long labels
    if len(label) > 14:
        words = label.split()
        mid = len(words) // 2
        l1 = ' '.join(words[:mid])
        l2 = ' '.join(words[mid:])
        lines.append(f'  <text x="{cx}" y="{cy-4}" text-anchor="middle" fill="#1e40af" font-size="11" font-weight="600">{l1}</text>')
        lines.append(f'  <text x="{cx}" y="{cy+10}" text-anchor="middle" fill="#1e40af" font-size="11" font-weight="600">{l2}</text>')
    else:
        lines.append(f'  <text x="{cx}" y="{cy+5}" text-anchor="middle" fill="#1e40af" font-size="11" font-weight="600">{label}</text>')

# Return box (single on right)
lines.append('  <rect x="680" y="280" width="160" height="50" rx="8" fill="#dcfce7" stroke="#22c55e" stroke-width="2"/>')
lines.append('  <text x="760" y="305" text-anchor="middle" fill="#166534" font-size="13" font-weight="700">Return agent_id</text>')
lines.append('  <text x="760" y="322" text-anchor="middle" fill="#166534" font-size="11">路由命中</text>')

# 404 box
lines.append('  <rect x="680" y="560" width="140" height="40" rx="8" fill="#fee2e2" stroke="#ef4444" stroke-width="1.5"/>')
lines.append('  <text x="750" y="585" text-anchor="middle" fill="#991b1b" font-size="12" font-weight="600">404 AgentNotFound</text>')

# Arrows: Start -> L1
lines.append('  <line x1="300" y1="90" x2="300" y2="110" stroke="#6b7280" stroke-width="1.5" marker-end="url(#ab)"/>')

# L1 Yes -> Return
lines.append('  <path d="M 430 150 L 500 150 L 500 305 L 680 305" stroke="#2563eb" stroke-width="1.5" fill="none" marker-end="url(#ab)"/>')
lines.append('  <rect x="440" y="140" width="30" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="455" y="152" text-anchor="middle" fill="#2563eb" font-size="10" font-weight="600">Yes</text>')

# L1 No -> L2
lines.append('  <line x1="300" y1="190" x2="300" y2="230" stroke="#6b7280" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('  <rect x="305" y="200" width="24" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="317" y="212" text-anchor="middle" fill="#6b7280" font-size="10" font-weight="600">No</text>')

# L2 Yes -> Return
lines.append('  <path d="M 420 270 L 500 270 L 500 305" stroke="#2563eb" stroke-width="1.5" fill="none" marker-end="url(#ab)"/>')
lines.append('  <rect x="430" y="260" width="30" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="445" y="272" text-anchor="middle" fill="#2563eb" font-size="10" font-weight="600">Yes</text>')

# L2 No -> L3
lines.append('  <line x1="300" y1="310" x2="300" y2="350" stroke="#6b7280" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('  <rect x="305" y="320" width="24" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="317" y="332" text-anchor="middle" fill="#6b7280" font-size="10" font-weight="600">No</text>')

# L3 Yes -> Return
lines.append('  <path d="M 420 390 L 500 390 L 500 330" stroke="#2563eb" stroke-width="1.5" fill="none" marker-end="url(#ab)"/>')
lines.append('  <rect x="430" y="380" width="30" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="445" y="392" text-anchor="middle" fill="#2563eb" font-size="10" font-weight="600">Yes</text>')

# L3 No -> L4
lines.append('  <line x1="300" y1="430" x2="300" y2="470" stroke="#6b7280" stroke-width="1.5" marker-end="url(#ab)"/>')
lines.append('  <rect x="305" y="440" width="24" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="317" y="452" text-anchor="middle" fill="#6b7280" font-size="10" font-weight="600">No</text>')

# L4 Yes -> Return
lines.append('  <path d="M 420 510 L 500 510 L 500 330" stroke="#2563eb" stroke-width="1.5" fill="none" marker-end="url(#ab)"/>')
lines.append('  <rect x="430" y="500" width="30" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="445" y="512" text-anchor="middle" fill="#2563eb" font-size="10" font-weight="600">Yes</text>')

# L4 No -> 404
lines.append('  <path d="M 300 550 L 300 580 L 680 580" stroke="#dc2626" stroke-width="1.5" fill="none" marker-end="url(#ar)"/>')
lines.append('  <rect x="305" y="560" width="24" height="16" fill="#ffffff" opacity="0.95"/>')
lines.append('  <text x="317" y="572" text-anchor="middle" fill="#dc2626" font-size="10" font-weight="600">No</text>')

# Right-side descriptions
lines.append('  <text x="860" y="305" text-anchor="middle" fill="#6b7280" font-size="11">命中即返回</text>')
lines.append('  <text x="860" y="580" text-anchor="middle" fill="#6b7280" font-size="11">全部未命中</text>')

lines.append('</svg>')

with open('/Users/szb/VibeCoding/Routers/diagrams/routing-flowchart.svg', 'w') as f:
    f.write('\n'.join(lines))

subprocess.run(['rsvg-convert', '/Users/szb/VibeCoding/Routers/diagrams/routing-flowchart.svg', '-o', '/dev/null'], check=True)
subprocess.run(['rsvg-convert', '-w', '1920', '/Users/szb/VibeCoding/Routers/diagrams/routing-flowchart.svg', '-o', '/Users/szb/VibeCoding/Routers/diagrams/routing-flowchart.png'], check=True)
print('OK: routing-flowchart.svg + .png')
