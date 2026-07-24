import json
import boto3
import os
import random
from datetime import datetime, timezone

REGION = os.environ.get('AWS_REGION', 'eu-central-1')
ACCOUNT = os.environ.get('ACCOUNT', '123456789012')

# Vehicle data used across pages
VEHICLES = [
    {"vin": "WBA7E2C50JG123401", "make": "BMW", "model": "530e", "type": "PHEV", "fleet": "FLT-001", "year": 2024},
    {"vin": "WBA7E2C50JG123402", "make": "BMW", "model": "540i", "type": "ICE", "fleet": "FLT-001", "year": 2023},
    {"vin": "WBA8B9G34KG123403", "make": "BMW", "model": "X5", "type": "ICE", "fleet": "FLT-001", "year": 2024},
    {"vin": "WBA3A5G59DN123405", "make": "BMW", "model": "iX", "type": "BEV", "fleet": "FLT-002", "year": 2025},
    {"vin": "WBA3A5G59DN123406", "make": "BMW", "model": "i4", "type": "BEV", "fleet": "FLT-002", "year": 2024},
    {"vin": "5YJ3E1EA5LF123411", "make": "Tesla", "model": "Model 3", "type": "BEV", "fleet": "FLT-002", "year": 2024},
    {"vin": "5YJSA1E26MF123413", "make": "Tesla", "model": "Model S", "type": "BEV", "fleet": "FLT-003", "year": 2025},
    {"vin": "5YJXCDE20HF123415", "make": "Tesla", "model": "Model X", "type": "BEV", "fleet": "FLT-001", "year": 2024},
    {"vin": "1FA6P8CF5L5123421", "make": "Ford", "model": "Mustang Mach-E", "type": "BEV", "fleet": "FLT-003", "year": 2024},
    {"vin": "1FA6P8CF5L5123423", "make": "Ford", "model": "F-150 Lightning", "type": "BEV", "fleet": "FLT-004", "year": 2025},
    {"vin": "WDD2060421A123431", "make": "Mercedes", "model": "EQS", "type": "BEV", "fleet": "FLT-001", "year": 2025},
    {"vin": "WDD2060421A123434", "make": "Mercedes", "model": "EQE", "type": "BEV", "fleet": "FLT-002", "year": 2023},
    {"vin": "WBS4Z9C59LA123408", "make": "BMW", "model": "M4", "type": "ICE", "fleet": "—", "year": 2024},
    {"vin": "WDD2060421A123439", "make": "Mercedes", "model": "AMG GT", "type": "ICE", "fleet": "—", "year": 2024},
]

FLEETS = [
    {"id": "FLT-001", "name": "Meridian Logistics", "owner": "Meridian Transport Corp", "region": "us-east-1", "count": 120},
    {"id": "FLT-002", "name": "Pacific Coast Transit", "owner": "Pacific Coast Holdings LLC", "region": "us-west-2", "count": 85},
    {"id": "FLT-003", "name": "Alpine Rental Group", "owner": "Alpine Mobility Inc", "region": "eu-west-1", "count": 200},
    {"id": "FLT-004", "name": "Great Plains Freight", "owner": "Great Plains Logistics Co", "region": "us-central-1", "count": 65},
    {"id": "FLT-005", "name": "Coastal Express Fleet", "owner": "Coastal Express Delivery", "region": "us-west-1", "count": 45},
]


def get_page(event):
    """Extract page from query params."""
    params = event.get('queryStringParameters') or {}
    return params.get('page', 'overview')


def wrap_page(body_content, active_page, incident_active, now):
    """Wrap page content with shared nav and CSS."""
    pages = [
        ("overview", "Overview"),
        ("fleet", "Fleet"),
        ("telemetry", "Telemetry"),
        ("ota", "OTA"),
        ("diagnostics", "Diagnostics"),
        ("trips", "Trips"),
        ("commands", "Commands"),
        ("ecus", "ECU Registry"),
    ]
    nav_links = ""
    for pid, label in pages:
        active_cls = ' class="active"' if pid == active_page else ''
        nav_links += f'<a href="?page={pid}"{active_cls}>{label}</a>'

    status_html = ''

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>MotorOS &mdash; Connected Vehicle Platform</title>
    <meta http-equiv="refresh" content="10">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; }}
        .nav {{ background: #161b22; padding: 12px 32px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #21262d; }}
        .nav-left {{ display: flex; align-items: center; gap: 24px; }}
        .logo {{ font-size: 18px; font-weight: 700; color: #fff; }}
        .logo span {{ color: #58a6ff; }}
        .nav-links {{ display: flex; gap: 4px; }}
        .nav-links a {{ color: #8b949e; text-decoration: none; font-size: 13px; padding: 5px 10px; border-radius: 6px; transition: background 0.15s; }}
        .nav-links a:hover {{ background: #21262d; color: #c9d1d9; }}
        .nav-links a.active {{ color: #fff; background: #21262d; }}
        .nav-right {{ display: flex; align-items: center; gap: 12px; color: #8b949e; font-size: 12px; }}
        .dot-live {{ width: 8px; height: 8px; background: #3fb950; border-radius: 50%; }}
        .incident-banner {{ background: linear-gradient(90deg, #f8514910 0%, #f8514905 100%); border-bottom: 1px solid #f8514940; color: #f85149; padding: 10px 32px; font-weight: 600; font-size: 13px; }}
        .content {{ padding: 24px 32px; max-width: 1600px; }}
        .section {{ margin-bottom: 20px; }}
        .section-header {{ font-size: 13px; font-weight: 600; color: #f0f6fc; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }}
        .section-header .count {{ background: #21262d; color: #8b949e; padding: 2px 7px; border-radius: 10px; font-size: 11px; font-weight: 500; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; }}
        .stat {{ background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 14px 16px; }}
        .stat-value {{ font-size: 24px; font-weight: 700; color: #fff; }}
        .stat-value.danger {{ color: #f85149; }}
        .stat-value.warn {{ color: #d29922; }}
        .stat-label {{ color: #8b949e; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; background: #161b22; border-radius: 8px; overflow: hidden; border: 1px solid #21262d; font-size: 12px; }}
        th {{ text-align: left; padding: 8px 12px; background: #0d1117; color: #8b949e; font-size: 10px; text-transform: uppercase; font-weight: 600; letter-spacing: 0.3px; }}
        td {{ padding: 8px 12px; border-top: 1px solid #21262d; }}
        .vin {{ font-family: 'JetBrains Mono', monospace; color: #79c0ff; font-size: 11px; }}
        .time {{ color: #484f58; font-size: 11px; }}
        .error-row {{ text-align: center; padding: 28px; color: #f85149; font-weight: 500; font-size: 13px; }}
        .badge {{ padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px; }}
        .badge-green {{ background: #3fb95015; color: #3fb950; border: 1px solid #3fb95030; }}
        .badge-blue {{ background: #58a6ff15; color: #58a6ff; border: 1px solid #58a6ff30; }}
        .badge-red {{ background: #f8514915; color: #f85149; border: 1px solid #f8514930; }}
        .badge-yellow {{ background: #d2992215; color: #d29922; border: 1px solid #d2992230; }}
        .badge-gray {{ background: #48505815; color: #8b949e; border: 1px solid #48505830; }}
        .ecu-tag {{ background: #1f2a37; color: #7ee787; padding: 2px 5px; border-radius: 3px; font-size: 10px; font-family: monospace; font-weight: 600; }}
        .campaign-id {{ font-family: monospace; color: #79c0ff; font-size: 11px; }}
        .progress-bar {{ width: 70px; height: 5px; background: #21262d; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px; }}
        .progress-fill {{ height: 100%; border-radius: 3px; }}
        .powertrain-bev {{ color: #7ee787; font-size: 10px; font-weight: 600; background: #7ee78715; padding: 2px 5px; border-radius: 3px; }}
        .powertrain-phev {{ color: #d2a8ff; font-size: 10px; font-weight: 600; background: #d2a8ff15; padding: 2px 5px; border-radius: 3px; }}
        .powertrain-ice {{ color: #8b949e; font-size: 10px; font-weight: 600; background: #8b949e15; padding: 2px 5px; border-radius: 3px; }}
        .soc {{ color: #7ee787; font-weight: 600; }}
        .fuel {{ color: #d29922; }}
        .cell-v {{ color: #484f58; font-size: 10px; font-family: monospace; }}
        .tire-ok {{ color: #8b949e; font-family: monospace; font-size: 11px; }}
        .tire-warn {{ color: #d29922; font-family: monospace; font-size: 11px; font-weight: 600; }}
        .dtc-critical {{ font-family: monospace; color: #f85149; font-weight: 700; font-size: 12px; }}
        .dtc-warning {{ font-family: monospace; color: #d29922; font-weight: 700; font-size: 12px; }}
        .dtc-info {{ font-family: monospace; color: #58a6ff; font-weight: 700; font-size: 12px; }}
        .severity-critical {{ color: #f85149; font-size: 10px; font-weight: 600; }}
        .severity-warning {{ color: #d29922; font-size: 10px; font-weight: 600; }}
        .severity-info {{ color: #58a6ff; font-size: 10px; font-weight: 600; }}
        .page-title {{ font-size: 16px; font-weight: 600; color: #f0f6fc; margin-bottom: 16px; }}
        @keyframes pulse-dot {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
    </style>
</head>
<body>
    <div class="nav">
        <div class="nav-left">
            <div class="logo">&#9889; Motor<span>OS</span></div>
            <div class="nav-links">{nav_links}</div>
        </div>
        <div class="nav-right">
            <div class="dot-live"></div>
            <span>OPERATIONAL &middot; {now.strftime('%H:%M:%S')} UTC</span>
        </div>
    </div>
    {status_html}
    <div class="content">
        {body_content}
    </div>
</body>
</html>"""


def page_overview(incident_active, dtc_count):
    """Main overview dashboard."""
    online_vehicles = random.randint(8200, 9100) if not incident_active else random.randint(3800, 4200)
    active_dtcs = dtc_count if dtc_count > 0 else (4 if not incident_active else random.randint(12, 18))
    ecu_failures = 3 if not incident_active else random.randint(47, 68)
    active_trips = random.randint(3400, 4200) if not incident_active else random.randint(1800, 2400)

    # Generate time-series data for graphs (last 30 minutes, 1-min intervals)
    now_min = datetime.now(timezone.utc).minute
    connectivity_points = []
    dtc_points = []
    for i in range(30):
        mins_ago = 29 - i
        if incident_active and mins_ago < 8:
            # After injection: connectivity drops gradually, DTCs spike
            conn_val = 9100 - (8 - mins_ago) * random.randint(200, 400)
            dtc_val = 4 + (8 - mins_ago) * random.randint(1, 3)
        elif incident_active and mins_ago < 12:
            # Transition zone
            conn_val = random.randint(8800, 9100)
            dtc_val = random.randint(4, 7)
        else:
            # Normal: stable connectivity, low DTCs
            conn_val = random.randint(8900, 9150)
            dtc_val = random.randint(2, 5)
        connectivity_points.append(conn_val)
        dtc_points.append(dtc_val)

    # SVG chart helper
    def make_svg_chart(points, height, y_min, y_max, color, threshold=None, threshold_color="#f85149"):
        width = 480
        h = height
        padding_top = 5
        padding_bottom = 5
        usable_h = h - padding_top - padding_bottom
        n = len(points)
        step = width / (n - 1)

        def y_pos(val):
            ratio = (val - y_min) / (y_max - y_min) if y_max > y_min else 0.5
            return padding_top + usable_h * (1 - ratio)

        path_points = " ".join([f"{'M' if i == 0 else 'L'}{i*step:.1f},{y_pos(points[i]):.1f}" for i in range(n)])

        # Fill area under line
        fill_points = f"M0,{y_pos(points[0]):.1f} " + " ".join([f"L{i*step:.1f},{y_pos(points[i]):.1f}" for i in range(1, n)])
        fill_points += f" L{(n-1)*step:.1f},{h} L0,{h} Z"

        svg = f'<svg width="{width}" height="{h}" style="display:block;">'
        # Grid lines
        for gy in range(4):
            gy_pos = padding_top + (usable_h / 3) * gy
            svg += f'<line x1="0" y1="{gy_pos:.0f}" x2="{width}" y2="{gy_pos:.0f}" stroke="#21262d" stroke-width="0.5"/>'
        # Threshold line
        if threshold is not None:
            ty = y_pos(threshold)
            svg += f'<line x1="0" y1="{ty:.1f}" x2="{width}" y2="{ty:.1f}" stroke="{threshold_color}" stroke-width="1" stroke-dasharray="4,3" opacity="0.6"/>'
        # Fill
        svg += f'<path d="{fill_points}" fill="{color}" opacity="0.1"/>'
        # Line
        svg += f'<path d="{path_points}" fill="none" stroke="{color}" stroke-width="1.5"/>'
        # Current value dot
        svg += f'<circle cx="{(n-1)*step}" cy="{y_pos(points[-1]):.1f}" r="3" fill="{color}"/>'
        svg += '</svg>'
        return svg

    connectivity_chart = make_svg_chart(connectivity_points, 80, 5000, 10000, "#58a6ff")
    dtc_chart = make_svg_chart(dtc_points, 80, 0, 20, "#d29922", threshold=8)

    # Time labels for x-axis
    time_labels = f'<div style="display:flex;justify-content:space-between;color:#484f58;font-size:10px;margin-top:2px;"><span>-30m</span><span>-20m</span><span>-10m</span><span>now</span></div>'

    charts_html = f"""
        <div class="grid-2" style="margin-bottom:20px;">
            <div class="section" style="margin-bottom:0;">
                <div class="section-header">Vehicles Reporting Telemetry <span class="count">{connectivity_points[-1]:,}</span></div>
                <div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px;">
                    {connectivity_chart}
                    {time_labels}
                </div>
            </div>
            <div class="section" style="margin-bottom:0;">
                <div class="section-header">Active DTC Rate <span class="count">{dtc_points[-1]} codes</span></div>
                <div style="background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px;">
                    {dtc_chart}
                    {time_labels}
                    <div style="color:#484f58;font-size:10px;margin-top:4px;">&#x2500;&#x2500; <span style="color:#f85149">alarm threshold (8)</span></div>
                </div>
            </div>
        </div>
    """

    # Telemetry rows — always show data, during incident some are stale
    telemetry_rows = ""
    for idx, v in enumerate(VEHICLES[:8]):
        speed = random.randint(0, 140)
        if incident_active and idx < 3:
            ago = random.randint(45, 180)  # stale during incident
        else:
            ago = random.randint(2, 30)
        temp_c = random.randint(32, 98)
        if v["type"] == "BEV":
            soc = random.randint(12, 96)
            cell_min = round(random.uniform(3.18, 3.52), 2)
            cell_max = round(random.uniform(3.98, 4.18), 2)
            energy_col = f'<td><span class="soc">{soc}%</span> <span class="cell-v">{cell_min}&ndash;{cell_max}V</span></td>'
        elif v["type"] == "PHEV":
            soc = random.randint(15, 85)
            fuel = random.randint(30, 90)
            energy_col = f'<td><span class="soc">{soc}%</span> + <span class="fuel">{fuel}% fuel</span></td>'
        else:
            fuel = random.randint(15, 92)
            energy_col = f'<td><span class="fuel">{fuel}% fuel</span></td>'
        tp = [round(random.uniform(228, 252), 0) for _ in range(4)]
        if random.random() < 0.08:
            tp[random.randint(0, 3)] = round(random.uniform(175, 195), 0)
        low_tire = any(p < 200 for p in tp)
        tp_display = f'<span class="{"tire-warn" if low_tire else "tire-ok"}">{int(tp[0])}/{int(tp[1])}/{int(tp[2])}/{int(tp[3])}</span>'
        telemetry_rows += f"""<tr>
            <td><span class="vin">{v['vin']}</span></td>
            <td>{v['make']} {v['model']}</td>
            <td><span class="powertrain-{v['type'].lower()}">{v['type']}</span></td>
            <td>{speed} km/h</td>
            {energy_col}
            <td>{tp_display}</td>
            <td>{temp_c}&deg;C</td>
            <td class="time">{ago}s ago</td>
        </tr>"""

    # OTA campaigns — same view regardless of incident (subtle: no obvious red)
    campaign_rows = """
    <tr><td class="campaign-id">campaign-2025-tcu-4.3.0</td><td><span class="ecu-tag">TCU</span> TCU-4.3.0</td>
        <td>FLT-001</td><td>120</td>
        <td><div class="progress-bar"><div class="progress-fill" style="width:39%;background:#58a6ff"></div></div> 47/120</td>
        <td><span class="badge badge-blue">ROLLING OUT</span></td></tr>
    <tr><td class="campaign-id">campaign-2025-ivi-3.1.4</td><td><span class="ecu-tag">IVI</span> IVI-3.1.4</td>
        <td>FLT-003</td><td>200</td>
        <td><div class="progress-bar"><div class="progress-fill" style="width:44%;background:#58a6ff"></div></div> 89/200</td>
        <td><span class="badge badge-blue">ROLLING OUT</span></td></tr>
    <tr><td class="campaign-id">campaign-2025-bms-2.8.1</td><td><span class="ecu-tag">BMS</span> BMS-2.8.1</td>
        <td>FLT-004</td><td>65</td>
        <td><div class="progress-bar"><div class="progress-fill" style="width:100%;background:#3fb950"></div></div> 65/65</td>
        <td><span class="badge badge-green">COMPLETED</span></td></tr>
    <tr><td class="campaign-id">campaign-2025-vcu-2.4.0</td><td><span class="ecu-tag">VCU</span> VCU-2.4.0</td>
        <td>FLT-002</td><td>85</td>
        <td><div class="progress-bar"><div class="progress-fill" style="width:0%;background:#484f58"></div></div> 0/85</td>
        <td><span class="badge badge-gray">PENDING</span></td></tr>"""

    # DTCs — always same view, the graph is the only clue
    dtc_rows = """
    <tr><td><span class="vin">5YJXCDE20HF123416</span></td><td>Tesla Model X</td>
        <td><span class="dtc-warning">P0AA6</span></td><td>Battery Voltage System Isolation Fault</td>
        <td><span class="ecu-tag">BMS</span></td><td><span class="severity-warning">WARNING</span></td><td>9</td><td>2h ago</td></tr>
    <tr><td><span class="vin">WDD2060421A123434</span></td><td>Mercedes EQE</td>
        <td><span class="dtc-critical">U0401</span></td><td>Invalid Data Received From ECM/PCM</td>
        <td><span class="ecu-tag">EPS</span></td><td><span class="severity-critical">CRITICAL</span></td><td>18</td><td>5h ago</td></tr>
    <tr><td><span class="vin">WBA3A5G59DN123407</span></td><td>BMW i7</td>
        <td><span class="dtc-warning">P1A00</span></td><td>Drive Motor A Control Module</td>
        <td><span class="ecu-tag">VCU</span></td><td><span class="severity-warning">WARNING</span></td><td>2</td><td>8h ago</td></tr>"""

    return f"""
        {charts_html}
        <div class="stats">
            <div class="stat"><div class="stat-value">12,450</div><div class="stat-label">Connected Vehicles</div></div>
            <div class="stat"><div class="stat-value">{online_vehicles:,}</div><div class="stat-label">Reporting Telemetry</div></div>
            <div class="stat"><div class="stat-value">{active_trips:,}</div><div class="stat-label">Active Trips</div></div>
            <div class="stat"><div class="stat-value{' warn' if active_dtcs > 10 else ''}">{active_dtcs}</div><div class="stat-label">Active DTCs</div></div>
            <div class="stat"><div class="stat-value{' warn' if ecu_failures > 20 else ''}">{ecu_failures}</div><div class="stat-label">ECU Update Failures</div></div>
            <div class="stat"><div class="stat-value{' warn' if dtc_count > 8 else ''}">{dtc_count}</div><div class="stat-label">DTC Rate (1h)</div></div>
        </div>
        <div class="section">
            <div class="section-header">&#128225; Live Vehicle Telemetry <span class="count">8 vehicles</span></div>
            <table><tr><th>VIN</th><th>Vehicle</th><th>Powertrain</th><th>Speed</th><th>Energy / Charge</th><th>Tire kPa (FL/FR/RL/RR)</th><th>Coolant</th><th>Last Signal</th></tr>
            {telemetry_rows}</table>
        </div>
        <div class="grid-2">
            <div class="section">
                <div class="section-header">&#128260; OTA Campaigns</div>
                <table><tr><th>Campaign</th><th>Target ECU / FW</th><th>Fleet</th><th>Vehicles</th><th>Progress</th><th>Status</th></tr>
                {campaign_rows}</table>
            </div>
            <div class="section">
                <div class="section-header">&#128295; Active DTCs</div>
                <table><tr><th>VIN</th><th>Vehicle</th><th>DTC</th><th>Description</th><th>ECU</th><th>Severity</th><th>Count</th><th>Last Seen</th></tr>
                {dtc_rows}</table>
            </div>
        </div>
        <div class="section">
            <div class="section-header">&#128205; Geofences <span class="count">5 active</span></div>
            <table><tr><th>Geofence</th><th>Type</th><th>Fleet</th><th>Vehicles Inside</th><th>Violations (24h)</th><th>Status</th></tr>
            <tr><td>Seattle Metro</td><td>Operational Zone</td><td>FLT-002</td><td>{random.randint(18, 32)}</td><td>1</td><td><span class="badge badge-green">ACTIVE</span></td></tr>
            <tr><td>LAX Airport Perimeter</td><td>Restricted Zone</td><td>FLT-001</td><td>{random.randint(3, 8)}</td><td>0</td><td><span class="badge badge-green">ACTIVE</span></td></tr>
            <tr><td>EU Service Region (Frankfurt)</td><td>Service Boundary</td><td>FLT-003</td><td>{random.randint(80, 140)}</td><td>0</td><td><span class="badge badge-green">ACTIVE</span></td></tr>
            <tr><td>Denver Curfew Zone</td><td>Time-restricted</td><td>FLT-004</td><td>{random.randint(0, 5)}</td><td>{random.randint(0, 2)}</td><td><span class="badge badge-yellow">MONITORING</span></td></tr>
            <tr><td>Coastal Express Depot</td><td>Home Base</td><td>FLT-005</td><td>{random.randint(10, 25)}</td><td>0</td><td><span class="badge badge-green">ACTIVE</span></td></tr>
            </table>
        </div>"""


def page_fleet():
    """Fleet registry page with vehicle connectivity status."""
    fleet_rows = ""
    for f in FLEETS:
        online = random.randint(int(f['count'] * 0.7), f['count'])
        sleeping = random.randint(0, f['count'] - online)
        offline = f['count'] - online - sleeping
        fleet_rows += f"""<tr>
            <td><span class="campaign-id">{f['id']}</span></td>
            <td>{f['name']}</td><td>{f['owner']}</td><td>{f['region']}</td>
            <td>{f['count']}</td>
            <td><span class="soc">{online}</span> / <span class="fuel">{sleeping}</span> / <span class="time">{offline}</span></td>
            <td><span class="badge badge-green">ACTIVE</span></td></tr>"""

    vehicle_rows = ""
    conn_states = ["CONNECTED", "CONNECTED", "CONNECTED", "CONNECTED", "SLEEPING", "SLEEPING", "OFFLINE"]
    for v in VEHICLES:
        fw = random.choice(["TCU-4.2.0", "TCU-4.3.0", "TCU-4.1.0"])
        status = random.choice(["UP_TO_DATE", "UP_TO_DATE", "UP_TO_DATE", "PENDING_UPDATE", "UPDATE_FAILED"])
        status_cls = "badge-green" if status == "UP_TO_DATE" else "badge-yellow" if status == "PENDING_UPDATE" else "badge-red"
        conn = random.choice(conn_states)
        conn_cls = "badge-green" if conn == "CONNECTED" else "badge-yellow" if conn == "SLEEPING" else "badge-gray"
        ago = f"{random.randint(1, 30)}s ago" if conn == "CONNECTED" else f"{random.randint(2, 45)}m ago" if conn == "SLEEPING" else f"{random.randint(1, 72)}h ago"
        vehicle_rows += f"""<tr>
            <td><span class="vin">{v['vin']}</span></td>
            <td>{v['make']} {v['model']}</td><td>{v['year']}</td>
            <td><span class="powertrain-{v['type'].lower()}">{v['type']}</span></td>
            <td>{v['fleet']}</td>
            <td><span class="badge {conn_cls}">{conn}</span> <span class="time">{ago}</span></td>
            <td>{fw}</td>
            <td><span class="badge {status_cls}">{status}</span></td></tr>"""

    return f"""
        <div class="page-title">Fleet Registry</div>
        <div class="section">
            <div class="section-header">Fleets <span class="count">{len(FLEETS)}</span></div>
            <table><tr><th>Fleet ID</th><th>Name</th><th>Owner</th><th>Region</th><th>Vehicles</th><th>Connected / Sleeping / Offline</th><th>Status</th></tr>
            {fleet_rows}</table>
        </div>
        <div class="section">
            <div class="section-header">Vehicles <span class="count">{len(VEHICLES)} shown</span></div>
            <table><tr><th>VIN</th><th>Vehicle</th><th>Year</th><th>Powertrain</th><th>Fleet</th><th>Connectivity</th><th>TCU FW</th><th>FW Status</th></tr>
            {vehicle_rows}</table>
        </div>"""


def page_telemetry():
    """Full telemetry feed page."""
    rows = ""
    events = ["HEARTBEAT", "HEARTBEAT", "IGNITION_ON", "IGNITION_OFF", "TRIP_START", "TRIP_END",
              "SPEED_EVENT", "HARD_BRAKE", "HARD_ACCEL", "GEOFENCE_EXIT", "GEOFENCE_ENTRY",
              "CHARGING_START", "CHARGING_COMPLETE", "CHARGE_PLUG_IN", "CHARGE_PLUG_OUT",
              "LOW_BATTERY", "DOOR_OPEN", "DOOR_CLOSE", "CRASH_DETECTED", "TOW_DETECTED",
              "FIRMWARE_ERROR", "CURFEW_VIOLATION", "IDLE_WARNING"]
    for _ in range(20):
        v = random.choice(VEHICLES)
        evt = random.choice(events)
        speed = random.randint(0, 160)
        lat = round(random.uniform(25, 52), 4)
        lng = round(random.uniform(-122, 14), 4)
        ago = random.randint(1, 120)
        if v["type"] == "BEV":
            soc = random.randint(5, 98)
            energy = f'<span class="soc">{soc}%</span>'
        elif v["type"] == "PHEV":
            soc = random.randint(10, 80)
            fuel = random.randint(20, 90)
            energy = f'<span class="soc">{soc}%</span>/<span class="fuel">{fuel}%</span>'
        else:
            fuel = random.randint(10, 95)
            energy = f'<span class="fuel">{fuel}%</span>'
        tp = [int(random.uniform(225, 260)) for _ in range(4)]
        evt_cls = "dtc-critical" if evt in ["FIRMWARE_ERROR", "CRASH_DETECTED", "TOW_DETECTED"] else "dtc-warning" if evt in ["SPEED_EVENT", "HARD_BRAKE", "HARD_ACCEL", "GEOFENCE_EXIT", "LOW_BATTERY", "CURFEW_VIOLATION"] else ""
        rows += f"""<tr>
            <td class="time">{ago}s</td>
            <td><span class="vin">{v['vin']}</span></td>
            <td>{v['make']} {v['model']}</td>
            <td><span class="{evt_cls}">{evt}</span></td>
            <td>{speed} km/h</td>
            <td>{energy}</td>
            <td class="tire-ok">{tp[0]}/{tp[1]}/{tp[2]}/{tp[3]}</td>
            <td>{lat}, {lng}</td></tr>"""

    return f"""
        <div class="page-title">Telemetry Stream</div>
        <div class="section">
            <div class="section-header">Recent Events <span class="count">last 20</span></div>
            <table><tr><th>Age</th><th>VIN</th><th>Vehicle</th><th>Event</th><th>Speed</th><th>Energy</th><th>Tires (kPa)</th><th>Position</th></tr>
            {rows}</table>
        </div>"""


def page_ota():
    """OTA campaign management — split into Safety Recalls and Feature Updates."""
    # Safety Recalls (mandatory, regulatory)
    recalls = [
        ("RCL-2025-ADAS-001", "ADAS", "ADAS-1.5.0", "FLT-005", 45, 12, 33, "FAILED", "NHTSA-25-V-118", "Braking ECU unintended deceleration in regen mode"),
        ("RCL-2025-BMS-002", "BMS", "BMS-2.8.1", "FLT-004", 65, 65, 0, "COMPLETED", "NHTSA-25-V-092", "Cell balancing fault may cause thermal event"),
        ("RCL-2025-EPS-003", "EPS", "EPS-1.2.1", "FLT-001", 120, 47, 0, "IN_PROGRESS", "KBA-2025-0341", "Intermittent loss of power steering assist above 80 km/h"),
    ]
    recall_rows = ""
    for cid, ecu, fw, fleet, total, done, failed, status, ref, desc in recalls:
        pct = int((done / total) * 100) if total > 0 else 0
        color = "#3fb950" if status == "COMPLETED" else "#f85149" if status == "FAILED" else "#58a6ff"
        s_cls = "badge-green" if status == "COMPLETED" else "badge-red" if status == "FAILED" else "badge-blue"
        recall_rows += f"""<tr>
            <td class="campaign-id">{cid}</td>
            <td><span class="dtc-critical">{ref}</span></td>
            <td>{desc}</td>
            <td><span class="ecu-tag">{ecu}</span> {fw}</td>
            <td>{fleet}</td><td>{done}/{total}</td>
            <td><div class="progress-bar"><div class="progress-fill" style="width:{pct}%;background:{color}"></div></div> {pct}%</td>
            <td><span class="badge {s_cls}">{status}</span></td></tr>"""

    # Feature Updates (optional, progressive rollout)
    features = [
        ("OTA-2025-TCU-4.0.8", "TCU", "TCU-4.0.8", "FLT-001", 120, 118, 2, "COMPLETED", "Connectivity stability improvements"),
        ("OTA-2025-TCU-4.0.9", "TCU", "TCU-4.0.9", "FLT-002", 85, 85, 0, "COMPLETED", "5G modem firmware update"),
        ("OTA-2025-IVI-3.1.0", "IVI", "IVI-3.1.0", "FLT-003", 200, 197, 3, "COMPLETED", "Infotainment navigation + media refresh"),
        ("OTA-2025-TCU-4.3.0", "TCU", "TCU-4.3.0", "FLT-001", 120, 47, 3, "IN_PROGRESS", "V2X communication protocol support"),
        ("OTA-2025-IVI-3.1.4", "IVI", "IVI-3.1.4", "FLT-003", 200, 89, 1, "IN_PROGRESS", "Driver profile sync + new UI theme"),
        ("OTA-2025-VCU-2.4.0", "VCU", "VCU-2.4.0", "FLT-002", 85, 0, 0, "PENDING", "Regenerative braking efficiency tuning"),
    ]
    feature_rows = ""
    for cid, ecu, fw, fleet, total, done, failed, status, desc in features:
        pct = int((done / total) * 100) if total > 0 else 0
        color = "#3fb950" if status == "COMPLETED" else "#58a6ff" if status == "IN_PROGRESS" else "#484f58"
        s_cls = "badge-green" if status == "COMPLETED" else "badge-blue" if status == "IN_PROGRESS" else "badge-gray"
        feature_rows += f"""<tr>
            <td class="campaign-id">{cid}</td>
            <td>{desc}</td>
            <td><span class="ecu-tag">{ecu}</span> {fw}</td>
            <td>{fleet}</td><td>{done}/{total}</td>
            <td><div class="progress-bar"><div class="progress-fill" style="width:{pct}%;background:{color}"></div></div> {pct}%</td>
            <td><span class="badge {s_cls}">{status}</span></td></tr>"""

    return f"""
        <div class="page-title">OTA Campaign Management</div>
        <div class="stats">
            <div class="stat"><div class="stat-value">9</div><div class="stat-label">Total Campaigns</div></div>
            <div class="stat"><div class="stat-value danger">3</div><div class="stat-label">Safety Recalls</div></div>
            <div class="stat"><div class="stat-value">6</div><div class="stat-label">Feature Updates</div></div>
            <div class="stat"><div class="stat-value warn">1</div><div class="stat-label">Failed</div></div>
            <div class="stat"><div class="stat-value">3</div><div class="stat-label">In Progress</div></div>
        </div>
        <div class="section">
            <div class="section-header">&#9888;&#xFE0F; Safety Recalls (Mandatory) <span class="count">3</span></div>
            <table><tr><th>Campaign</th><th>Recall Ref</th><th>Description</th><th>ECU / FW</th><th>Fleet</th><th>Progress</th><th></th><th>Status</th></tr>
            {recall_rows}</table>
        </div>
        <div class="section">
            <div class="section-header">&#128260; Feature Updates (Optional) <span class="count">6</span></div>
            <table><tr><th>Campaign</th><th>Description</th><th>ECU / FW</th><th>Fleet</th><th>Progress</th><th></th><th>Status</th></tr>
            {feature_rows}</table>
        </div>"""


def page_diagnostics():
    """DTC diagnostics page."""
    dtcs = [
        ("WBA8B9G34KG123404", "BMW X3", "U0073", "Control Module Communication Bus Off", "GW", "CRITICAL", "ACTIVE", 12),
        ("WBA8B9G34KG123404", "BMW X3", "U0100", "Lost Communication with ECM/PCM", "TCU", "CRITICAL", "ACTIVE", 8),
        ("WBS4Z9C59LA123410", "BMW M5", "U0401", "Invalid Data Received From ECM/PCM", "ADAS", "CRITICAL", "ACTIVE", 5),
        ("WBS4Z9C59LA123410", "BMW M5", "C0561", "System Disabled Information Stored", "ADAS", "WARNING", "CONFIRMED", 3),
        ("5YJ3E1EA5LF123420", "Tesla Model 3", "P0A80", "Replace Energy Storage Unit", "BMS", "CRITICAL", "ACTIVE", 2),
        ("5YJXCDE20HF123416", "Tesla Model X", "P0AA6", "Battery Voltage System Isolation Fault", "BMS", "CRITICAL", "ACTIVE", 9),
        ("5YJXCDE20HF123416", "Tesla Model X", "P0A80", "Replace Energy Storage Unit", "BMS", "WARNING", "PENDING", 4),
        ("WDD2060421A123434", "Mercedes EQE", "U0401", "Invalid Data Received From ECM/PCM", "EPS", "CRITICAL", "ACTIVE", 18),
        ("WDD2060421A123434", "Mercedes EQE", "C0561", "System Disabled Information Stored", "VCU", "WARNING", "CONFIRMED", 6),
        ("WBA3A5G59DN123407", "BMW i7", "P1A00", "Drive Motor A Control Module", "VCU", "WARNING", "ACTIVE", 2),
        ("1FA6P8CF5L5123423", "Ford F-150 Lightning", "P0128", "Coolant Thermostat Below Regulating Temp", "ECM", "INFO", "ACTIVE", 1),
        ("WBA7E2C50JG123402", "BMW 540i", "U0073", "Control Module Communication Bus Off", "IVI", "INFO", "CLEARED", 3),
        ("WDD2060421A123439", "Mercedes AMG GT", "C0035", "Left Front Wheel Speed Sensor Circuit", "ADAS", "WARNING", "CLEARED", 11),
    ]
    rows = ""
    for vin, vehicle, code, desc, ecu, sev, status, count in dtcs:
        sev_cls = f"severity-{sev.lower()}"
        code_cls = f"dtc-{sev.lower()}" if sev != "INFO" else "dtc-info"
        s_cls = "badge-red" if status == "ACTIVE" else "badge-yellow" if status in ["CONFIRMED", "PENDING"] else "badge-gray"
        rows += f"""<tr>
            <td><span class="vin">{vin}</span></td><td>{vehicle}</td>
            <td><span class="{code_cls}">{code}</span></td><td>{desc}</td>
            <td><span class="ecu-tag">{ecu}</span></td>
            <td><span class="{sev_cls}">{sev}</span></td>
            <td><span class="badge {s_cls}">{status}</span></td><td>{count}</td></tr>"""

    critical = sum(1 for d in dtcs if d[5] == "CRITICAL" and d[6] == "ACTIVE")
    warning = sum(1 for d in dtcs if d[5] == "WARNING")
    return f"""
        <div class="page-title">Diagnostics &mdash; Trouble Codes</div>
        <div class="stats">
            <div class="stat"><div class="stat-value">{len(dtcs)}</div><div class="stat-label">Total DTCs</div></div>
            <div class="stat"><div class="stat-value danger">{critical}</div><div class="stat-label">Critical Active</div></div>
            <div class="stat"><div class="stat-value warn">{warning}</div><div class="stat-label">Warnings</div></div>
            <div class="stat"><div class="stat-value">5</div><div class="stat-label">Vehicles Affected</div></div>
        </div>
        <div class="section">
            <table><tr><th>VIN</th><th>Vehicle</th><th>DTC</th><th>Description</th><th>ECU</th><th>Severity</th><th>Status</th><th>Count</th></tr>
            {rows}</table>
        </div>"""


def page_trips():
    """Trip history page."""
    rows = ""
    for i in range(15):
        v = random.choice(VEHICLES)
        dist = round(random.uniform(5, 145), 1)
        dur = random.randint(10, 175)
        avg_speed = round(dist / (dur / 60), 1)
        max_speed = random.randint(int(avg_speed), min(int(avg_speed * 1.8), 180))
        harsh_b = random.randint(0, 3)
        harsh_a = random.randint(0, 2)
        idle = random.randint(0, 20)
        hour = random.randint(5, 22)
        if v["type"] in ["BEV", "PHEV"]:
            start_soc = random.randint(40, 98)
            end_soc = start_soc - random.randint(5, 30)
            kwh = round((start_soc - end_soc) * 0.65, 1)
            energy = f'{kwh} kWh ({start_soc}%&rarr;{end_soc}%)'
        else:
            liters = round(dist * random.uniform(0.06, 0.12), 1)
            energy = f'{liters} L'
        rows += f"""<tr>
            <td class="campaign-id">TRP-2025-{1000+i:04d}</td>
            <td><span class="vin">{v['vin']}</span></td><td>{v['make']} {v['model']}</td>
            <td>Today {hour:02d}:{random.randint(0,59):02d}</td>
            <td>{dist} km</td><td>{dur} min</td>
            <td>{avg_speed} km/h</td><td>{max_speed} km/h</td>
            <td>{energy}</td>
            <td>{harsh_b}</td><td>{harsh_a}</td><td>{idle} min</td></tr>"""

    return f"""
        <div class="page-title">Trip History</div>
        <div class="section">
            <div class="section-header">Recent Trips <span class="count">15 shown</span></div>
            <table><tr><th>Trip ID</th><th>VIN</th><th>Vehicle</th><th>Start</th><th>Distance</th><th>Duration</th><th>Avg Speed</th><th>Max Speed</th><th>Energy</th><th>Hard Brake</th><th>Hard Accel</th><th>Idle</th></tr>
            {rows}</table>
        </div>"""


def page_ecus():
    """ECU registry page."""
    ecu_types = ["IVI", "BMS", "ADAS", "TCU", "VCU", "ECM", "EPS", "HVAC", "GW"]
    sw_versions = {
        "IVI": ["IVI-3.1.4", "IVI-3.1.2", "IVI-3.0.8"],
        "BMS": ["BMS-2.8.1", "BMS-2.7.0"],
        "ADAS": ["ADAS-1.5.0", "ADAS-1.4.2"],
        "TCU": ["TCU-4.3.0", "TCU-4.2.0", "TCU-4.1.0", "TCU-4.0.9"],
        "VCU": ["VCU-2.3.1", "VCU-2.4.0"],
        "ECM": ["ECM-5.0.2", "ECM-4.8.1"],
        "EPS": ["EPS-1.2.0"],
        "HVAC": ["HVAC-1.4.0", "HVAC-1.3.2"],
        "GW": ["GW-3.0.5", "GW-2.9.1"],
    }
    rows = ""
    for v in VEHICLES[:10]:
        ecus = ["IVI", "ADAS", "TCU", "HVAC", "GW"]
        if v["type"] in ["BEV", "PHEV"]:
            ecus += ["BMS", "VCU"]
        else:
            ecus += ["ECM", "EPS"]
        for ecu in ecus:
            sw = random.choice(sw_versions.get(ecu, ["1.0.0"]))
            hw_rev = random.choice(["R1", "R2", "R3", "R4"])
            status = random.choices(["UP_TO_DATE", "PENDING_UPDATE", "UPDATE_FAILED"], weights=[85, 10, 5])[0]
            s_cls = "badge-green" if status == "UP_TO_DATE" else "badge-yellow" if status == "PENDING_UPDATE" else "badge-red"
            rows += f"""<tr>
                <td><span class="vin">{v['vin']}</span></td><td>{v['make']} {v['model']}</td>
                <td><span class="ecu-tag">{ecu}</span></td>
                <td>{ecu}-HW-{random.randint(1000,9999)}-{hw_rev}</td><td>{hw_rev}</td>
                <td>{sw}</td>
                <td><span class="badge {s_cls}">{status}</span></td></tr>"""

    return f"""
        <div class="page-title">ECU Registry</div>
        <div class="section">
            <div class="section-header">ECU Inventory <span class="count">10 vehicles shown</span></div>
            <table><tr><th>VIN</th><th>Vehicle</th><th>ECU</th><th>HW Part Number</th><th>HW Rev</th><th>SW Version</th><th>Status</th></tr>
            {rows}</table>
        </div>"""


def page_commands():
    """Remote commands log page."""
    commands = ["LOCK", "UNLOCK", "HONK_FLASH", "PRECONDITION_HVAC", "IMMOBILIZE",
                "REMOTE_START", "LOCATE", "SPEED_LIMIT_SET", "CURFEW_SET", "DIAGNOSTICS_REQUEST"]
    statuses = ["DELIVERED", "DELIVERED", "DELIVERED", "PENDING", "DELIVERED", "TIMEOUT", "DELIVERED"]
    actors = ["fleet-admin@motoros.io", "ops-admin@motoros.io", "dealer-portal-svc", "geofence-monitor-svc", "theft-detection-svc"]
    rows = ""
    for i in range(18):
        v = random.choice(VEHICLES)
        cmd = random.choice(commands)
        status = random.choice(statuses)
        actor = random.choice(actors)
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        s_cls = "badge-green" if status == "DELIVERED" else "badge-yellow" if status == "PENDING" else "badge-red"
        latency = f"{random.randint(800, 4500)}ms" if status == "DELIVERED" else "&mdash;"
        rows += f"""<tr>
            <td class="campaign-id">CMD-{random.randint(10000,99999)}</td>
            <td><span class="vin">{v['vin']}</span></td><td>{v['make']} {v['model']}</td>
            <td><span class="ecu-tag">{cmd}</span></td>
            <td>{actor}</td>
            <td>Today {hour:02d}:{minute:02d}</td>
            <td>{latency}</td>
            <td><span class="badge {s_cls}">{status}</span></td></tr>"""

    delivered = sum(1 for _ in range(18) if random.random() < 0.75)
    return f"""
        <div class="page-title">Remote Commands</div>
        <div class="stats">
            <div class="stat"><div class="stat-value">247</div><div class="stat-label">Commands Today</div></div>
            <div class="stat"><div class="stat-value">94.2%</div><div class="stat-label">Delivery Rate</div></div>
            <div class="stat"><div class="stat-value">1.8s</div><div class="stat-label">Avg Latency</div></div>
            <div class="stat"><div class="stat-value warn">3</div><div class="stat-label">Timeouts</div></div>
        </div>
        <div class="section">
            <div class="section-header">Command Log <span class="count">last 18</span></div>
            <table><tr><th>Command ID</th><th>VIN</th><th>Vehicle</th><th>Command</th><th>Initiated By</th><th>Time</th><th>Latency</th><th>Status</th></tr>
            {rows}</table>
        </div>"""


def handler(event, context):
    cw = boto3.client('cloudwatch', region_name=REGION)

    # Check if any motoros alarms are firing
    try:
        alarms_firing = cw.describe_alarms(AlarmNamePrefix='motoros3', StateValue='ALARM')['MetricAlarms']
    except:
        alarms_firing = []

    # Check the ActiveDTCCount metric (pushed by health-monitor every 30s)
    dtc_count = 0
    try:
        from datetime import timedelta
        resp = cw.get_metric_statistics(
            Namespace='MotorOS/VehicleHealth',
            MetricName='ActiveDTCCount',
            StartTime=datetime.now(timezone.utc) - timedelta(minutes=5),
            EndTime=datetime.now(timezone.utc),
            Period=60,
            Statistics=['Maximum']
        )
        if resp['Datapoints']:
            dtc_count = int(max(dp['Maximum'] for dp in resp['Datapoints']))
    except:
        dtc_count = 0

    incident_active = dtc_count > 8 or len(alarms_firing) > 0
    now = datetime.now(timezone.utc)
    page = get_page(event)

    if page == "fleet":
        body = page_fleet()
    elif page == "telemetry":
        body = page_telemetry()
    elif page == "ota":
        body = page_ota()
    elif page == "diagnostics":
        body = page_diagnostics()
    elif page == "trips":
        body = page_trips()
    elif page == "ecus":
        body = page_ecus()
    elif page == "commands":
        body = page_commands()
    else:
        body = page_overview(incident_active, dtc_count)

    html = wrap_page(body, page, incident_active, now)
    return {"statusCode": 200, "headers": {"Content-Type": "text/html; charset=utf-8"}, "body": html}
