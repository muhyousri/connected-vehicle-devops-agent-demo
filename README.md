# MotorOS Demo Environment

Connected-vehicle platform demo for AWS DevOps Agent workshops.

## What This Deploys

- EKS cluster (3 nodes) with 12 microservices across 2 namespaces
- Aurora PostgreSQL (writer + reader) with seeded automotive data
- Kinesis stream with live vehicle telemetry producer
- SQS, ElastiCache, S3, CloudWatch alarms, SNS topic
- Platform dashboard and alert feed (API Gateway + Lambda)
- Health monitor that pushes pod metrics to CloudWatch
- Alarm bridge Lambda for DevOps Agent auto-trigger

## Prerequisites

- AWS CLI v2
- Node.js 18+
- AWS CDK CLI: `npm install -g aws-cdk`
- kubectl
- An AWS account with AdministratorAccess

## Step 1: DevOps Agent Setup (One-Time)

Complete this before deploying infrastructure.

1. Open the [DevOps Agent console](https://console.aws.amazon.com/devops-agent/) in your target region.
2. [Create an Agent Space](https://docs.aws.amazon.com/devopsagent/latest/userguide/getting-started-with-aws-devops-agent-creating-an-agent-space.html). Select "Auto-create a new AWS DevOps Agent role" for both the monitor role and operator app role.
3. [Configure a DevOps Agent Actions Role](https://docs.aws.amazon.com/devopsagent/latest/userguide/getting-started-with-aws-devops-agent-creating-an-agent-space.html) with write permissions (SNS, CloudWatch, EKS).
4. Note the Agent Space IAM role ARNs. Find them in IAM console under roles containing `DevOpsAgentRole-AgentSpace` and `DevOpsAgentRole-WebappAdmin`. Pass **all** of them comma-separated to the CDK deploy command. You can list them with:
   ```bash
   aws iam list-roles --query 'Roles[?contains(RoleName,`DevOpsAgentRole`)].Arn' --output text | tr '\t' ','
   ```
5. **(Optional: automated alarm-to-agent trigger)** Under Capabilities > Webhooks, [create a webhook](https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-invoking-devops-agent-through-webhook.html). Save the endpoint URL and secret. These values are passed to the CDK deploy command to enable the DevOps Agent to start investigations automatically when alarms fire.

## Step 2: Deploy

```bash
cd infra && npm install

# Set your target region and account
export AWS_REGION=eu-central-1
export AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

# Bootstrap CDK (first time only)
cdk bootstrap aws://$AWS_ACCOUNT/$AWS_REGION

# Deploy all stacks (~17 min)
cdk deploy --all \
  -c region=$AWS_REGION \
  -c devopsAgentRoleArns="arn:aws:iam::$AWS_ACCOUNT:role/service-role/DevOpsAgentRole-AgentSpace-XXXX" \
  --require-approval never
```

To demonstrate automated DevOps Agent trigger on alarm, include the webhook parameters:

```bash
cdk deploy --all \
  -c region=$AWS_REGION \
  -c devopsAgentRoleArns="arn:aws:iam::$AWS_ACCOUNT:role/service-role/DevOpsAgentRole-AgentSpace-XXXX" \
  -c devopsAgentWebhookUrl="https://event-ai.$AWS_REGION.api.aws/webhook/generic/XXXX" \
  -c devopsAgentWebhookSecret="XXXX" \
  --require-approval never
```

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `region` | Target AWS region | No (default: `eu-central-1`) |
| `deployerRoleName` | IAM role name for kubectl access | No (default: `Admin`) |
| `devopsAgentRoleArns` | Comma-separated DevOps Agent IAM role ARNs for EKS access | No |
| `devopsAgentWebhookUrl` | DevOps Agent webhook URL for automated trigger | No |
| `devopsAgentWebhookSecret` | DevOps Agent webhook HMAC secret | No |

## Step 3: Verify

```bash
# Configure kubectl
aws eks update-kubeconfig --name motoros-cluster --region eu-central-1

# Check pods
kubectl get pods -n motoros-prod

# Get dashboard URLs
aws cloudformation describe-stacks --stack-name motoros-Dashboard --region eu-central-1 \
  --query 'Stacks[0].Outputs[]' --output table
```

## Incident Injection

```bash
cd chaos

# Break the system (pods OOM, Kinesis flood)
./inject-incident.sh

# Restore
./reset-incident.sh
```

The alarm fires naturally within ~2 minutes. If the webhook is configured, the DevOps Agent starts an investigation automatically.

## Tear Down

```bash
cd infra
cdk destroy --all --force -c region=eu-central-1
```

## Project Structure

```
infra/              CDK stacks (TypeScript)
services/           12 FastAPI microservices
dashboard/          Platform UI + Alert Feed + Alarm Bridge Lambdas
chaos/              Incident inject/reset scripts
seed/               Aurora seed data + Lambda layer
skills/             DevOps Agent skill definitions
docs/               Demo flow guide
```
