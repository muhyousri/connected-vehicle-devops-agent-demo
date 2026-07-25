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
    
    # Parse alarm data — could come via SNS or direct invocation
    alarm_data = {}
    if 'Records' in event:
        # SNS notification wrapper
        sns_message = event['Records'][0]['Sns']['Message']
        alarm_data = json.loads(sns_message) if isinstance(sns_message, str) else sns_message
    elif 'alarmData' in event:
        # Direct CloudWatch alarm action
        alarm_data = event.get('alarmData', {})
    else:
        alarm_data = event

    # Extract alarm fields from CloudWatch alarm notification format
    alarm_name = alarm_data.get('AlarmName', alarm_data.get('alarmName', 'Unknown'))
    alarm_desc = alarm_data.get('AlarmDescription', alarm_data.get('description', ''))
    new_state = alarm_data.get('NewStateValue', alarm_data.get('state', {}).get('value', 'ALARM'))
    reason = alarm_data.get('NewStateReason', alarm_data.get('state', {}).get('reason', ''))
    region = alarm_data.get('Region', os.environ.get('AWS_REGION', 'eu-central-1'))
    account_id = alarm_data.get('AWSAccountId', '')
    alarm_arn = alarm_data.get('AlarmArn', '')
    trigger = alarm_data.get('Trigger', {})
    timestamp = alarm_data.get('StateChangeTime', datetime.utcnow().isoformat())

    # Only trigger for ALARM state
    if new_state != 'ALARM':
        print(f"State is {new_state}, not ALARM — skipping")
        return {'statusCode': 200, 'body': f'State {new_state}, skipping'}
    
    # Build metric info from Trigger
    metric_info = ""
    if trigger:
        metric_info = f"{trigger.get('Namespace','')}/{trigger.get('MetricName','')}"

    description = f"CloudWatch Alarm: {alarm_name}\n"
    description += f"Account: {account_id}, Region: {region}\n"
    description += f"Reason: {reason}"
    if alarm_desc:
        description += f"\nDescription: {alarm_desc}"
    if metric_info:
        description += f"\nMetric: {metric_info}"
    
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
                "alarmArn": alarm_arn,
                "trigger": trigger
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
        return {'statusCode': 200, 'body': f'Investigation triggered for {alarm_name}'}
    else:
        raise Exception(f"Webhook failed: {response.status}")
