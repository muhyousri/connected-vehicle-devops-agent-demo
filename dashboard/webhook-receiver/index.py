import json
import boto3
import datetime
import os

LOG_GROUP = "/aws/lambda/motoros3-webhook-receiver"
REGION = os.environ.get('AWS_REGION', 'eu-central-1')

def handler(event, context):
    method = event.get('httpMethod', 'POST')
    path = event.get('path', '')
    
    # POST /alert/clear — clear all alarms
    if method == 'POST' and 'clear' in path:
        cw = boto3.client('cloudwatch', region_name=REGION)
        alarms = cw.describe_alarms(AlarmNamePrefix='motoros3', StateValue='ALARM')['MetricAlarms']
        for a in alarms:
            cw.set_alarm_state(AlarmName=a['AlarmName'], StateValue='OK', StateReason='Manually cleared by operator')
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"cleared": len(alarms)})}
    
    # GET /alert — dashboard
    if method == 'GET':
        return serve_dashboard(event)
    
    # POST /alert — receive webhook
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"
    body = event.get('body', '')
    
    try:
        payload = json.loads(body) if body else {}
    except:
        payload = {"raw": body}
    
    msg_type = event.get('headers', {}).get('x-amz-sns-message-type', '') or event.get('headers', {}).get('X-Amz-Sns-Message-Type', '')
    if msg_type == 'SubscriptionConfirmation':
        import urllib.request
        subscribe_url = payload.get('SubscribeURL', '')
        if subscribe_url:
            urllib.request.urlopen(subscribe_url)
    
    alert = {"timestamp": timestamp, "type": msg_type or "Notification", "payload": payload}
    print(json.dumps(alert))
    
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"status": "received"})}

def serve_dashboard(event):
    logs_client = boto3.client('logs', region_name=REGION)
    cw = boto3.client('cloudwatch', region_name=REGION)
    
    # Get current alarm states
    alarms_firing = cw.describe_alarms(AlarmNamePrefix='motoros3', StateValue='ALARM')['MetricAlarms']
    alarm_count = len(alarms_firing)
    
    alerts_html = ""
    try:
        streams = logs_client.describe_log_streams(
            logGroupName=LOG_GROUP, orderBy='LastEventTime', descending=True, limit=3
        )
        for stream in streams.get('logStreams', [])[:3]:
            events = logs_client.get_log_events(
                logGroupName=LOG_GROUP, logStreamName=stream['logStreamName'], limit=20, startFromHead=False
            )
            for evt in reversed(events.get('events', [])):
                msg = evt['message'].strip()
                if msg.startswith('{') and 'payload' in msg:
                    try:
                        data = json.loads(msg)
                        if data.get('type') == 'SubscriptionConfirmation':
                            continue
                        ts = data.get('timestamp', '')[:19]
                        payload = data.get('payload', {})
                        sns_message = payload.get('Message', '')
                        try:
                            alarm_data = json.loads(sns_message) if sns_message else {}
                        except:
                            alarm_data = {}
                        
                        state = alarm_data.get('NewStateValue', 'UNKNOWN')
                        if state == 'ALARM':
                            badge = "🔴"; severity = "CRITICAL"; sev_class = "sev-critical"
                        elif state == 'OK':
                            badge = "🟢"; severity = "RESOLVED"; sev_class = "sev-ok"
                        else:
                            badge = "🟡"; severity = "WARNING"; sev_class = "sev-warn"
                        
                        reason = alarm_data.get('NewStateReason', 'Alert triggered')
                        if 'Threshold' in reason:
                            reason = "Metric threshold exceeded"
                        elif 'transition' in reason.lower():
                            reason = "State transition detected"
                        else:
                            reason = reason[:60] + "..." if len(reason) > 60 else reason
                        
                        alerts_html += f"""
                        <div class="alert-card {sev_class}">
                            <div class="alert-header">
                                <span class="badge-icon">{badge}</span>
                                <span class="alert-sev">{severity}</span>
                                <span class="alert-time">{ts}</span>
                            </div>
                            <div class="alert-reason">{reason}</div>
                        </div>"""
                    except:
                        pass
    except:
        pass
    
    if not alerts_html:
        alerts_html = '<div class="empty-state"><div class="empty-icon">📡</div><h3>Waiting for alerts...</h3></div>'
    
    status_bar = f'<div class="status-bar firing">🔴 {alarm_count} alarm{"s" if alarm_count != 1 else ""} firing</div>' if alarm_count > 0 else '<div class="status-bar ok">🟢 All clear</div>'
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>MotorOS — Alert Feed</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; padding: 24px; }}
        .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #21262d; }}
        .header h1 {{ font-size: 20px; color: #f0f6fc; }}
        .clear-btn {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; text-decoration: none; }}
        .clear-btn:hover {{ background: #30363d; color: #f0f6fc; }}
        .status-bar {{ padding: 10px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; margin-bottom: 16px; }}
        .status-bar.firing {{ background: #f8514915; color: #f85149; border: 1px solid #f8514930; }}
        .status-bar.ok {{ background: #3fb95015; color: #3fb950; border: 1px solid #3fb95030; }}
        .alert-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 14px 16px; margin-bottom: 10px; }}
        .alert-card.sev-critical {{ border-left: 3px solid #f85149; }}
        .alert-card.sev-ok {{ border-left: 3px solid #3fb950; }}
        .alert-card.sev-warn {{ border-left: 3px solid #d29922; }}
        .alert-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }}
        .badge-icon {{ font-size: 14px; }}
        .alert-sev {{ font-size: 11px; font-weight: 700; text-transform: uppercase; }}
        .sev-critical .alert-sev {{ color: #f85149; }}
        .sev-ok .alert-sev {{ color: #3fb950; }}
        .sev-warn .alert-sev {{ color: #d29922; }}
        .alert-time {{ color: #484f58; font-size: 12px; font-family: monospace; margin-left: auto; }}
        .alert-reason {{ color: #8b949e; font-size: 13px; }}
        .empty-state {{ text-align: center; padding: 40px; color: #8b949e; }}
        .empty-icon {{ font-size: 36px; margin-bottom: 12px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔔 Alert Feed</h1>
        <a class="clear-btn" href="#" onclick="fetch(window.location.href.replace('/alert','/alert/clear'),{{method:'POST'}}).then(()=>location.reload());return false;">🧹 Clear Alarms</a>
    </div>
    {status_bar}
    {alerts_html}
</body>
</html>"""
    
    return {"statusCode": 200, "headers": {"Content-Type": "text/html"}, "body": html}
