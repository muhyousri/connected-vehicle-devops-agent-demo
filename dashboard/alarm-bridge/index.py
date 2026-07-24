import json
import os
import hmac
import hashlib
import base64
import urllib3
import boto3
from datetime import datetime

http = urllib3.PoolManager()

def get_webhook_config():
    sm = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'eu-central-1'))
    secret = json.loads(sm.get_secret_value(SecretId=os.environ['WEBHOOK_SECRET_NAME'])['SecretString'])
    return secret['url'], secret['secret']

def lambda_handler(event, context):
    print(f"Received: {json.dumps(event)}")
    
    WEBHOOK_URL, WEBHOOK_SECRET = get_webhook_config()
    
    # Parse CloudWatch alarm event
    alarm_name = event.get('alarmData', {}).get('alarmName', 'Unknown')
    alarm_desc = event.get('alarmData', {}).get('configuration', {}).get('description', '')
    new_state = event.get('alarmData', {}).get('state', {}).get('value', 'ALARM')
    reason = event.get('alarmData', {}).get('state', {}).get('reason', '')
    timestamp = event.get('alarmData', {}).get('state', {}).get('timestamp', datetime.utcnow().isoformat())
    region = event.get('region', 'eu-central-1')
    account_id = event.get('accountId', '')
    
    # Only trigger for ALARM state
    if new_state != 'ALARM':
        return {'statusCode': 200, 'body': 'Not in ALARM state, skipping'}
    
    # Extract metric info
    metrics = event.get('alarmData', {}).get('configuration', {}).get('metrics', [])
    metric_info = ""
    if metrics:
        metric = metrics[0].get('metricStat', {}).get('metric', {})
        metric_info = f"\nMetric: {metric.get('namespace','')}/{metric.get('name','')}"
    
    description = f"CloudWatch Alarm: {alarm_name}\n"
    description += f"Account: {account_id}, Region: {region}\n"
    description += f"Reason: {reason}"
    if alarm_desc:
        description += f"\nDescription: {alarm_desc}"
    description += metric_info
    
    # Build DevOps Agent webhook payload
    payload = {
        "eventType": "incident",
        "incidentId": f"{alarm_name}-{timestamp}",
        "action": "created",
        "priority": "HIGH",
        "title": f"CloudWatch Alarm: {alarm_name}",
        "description": description,
        "timestamp": timestamp,
        "service": alarm_name,
        "data": {
            "metadata": {
                "alarmName": alarm_name,
                "region": region,
                "accountId": account_id,
                "newState": new_state,
                "reason": reason,
                "alarmArn": event.get('alarmArn', ''),
                "metrics": metrics
            }
        }
    }
    
    payload_json = json.dumps(payload)
    event_timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
    
    # HMAC signature
    signature_string = f"{event_timestamp}:{payload_json}"
    signature = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        signature_string.encode('utf-8'),
        hashlib.sha256
    ).digest()
    signature_b64 = base64.b64encode(signature).decode('utf-8')
    
    # Send webhook
    headers = {
        'Content-Type': 'application/json',
        'x-amzn-event-timestamp': event_timestamp,
        'x-amzn-event-signature': signature_b64
    }
    
    response = http.request('POST', WEBHOOK_URL, body=payload_json, headers=headers)
    print(f"Webhook response: {response.status} {response.data.decode('utf-8')}")
    
    if response.status in [200, 202]:
        return {'statusCode': 200, 'body': 'Investigation triggered'}
    else:
        raise Exception(f"Webhook failed: {response.status}")
