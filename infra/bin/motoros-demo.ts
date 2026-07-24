#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { VpcStack } from '../lib/vpc-stack';
import { EksStack } from '../lib/eks-stack';
import { AuroraStack } from '../lib/aurora-stack';
import { KinesisStack } from '../lib/kinesis-stack';
import { SqsStack } from '../lib/sqs-stack';
import { ElastiCacheStack } from '../lib/elasticache-stack';
import { S3Stack } from '../lib/s3-stack';
import { AlertingStack } from '../lib/alerting-stack';
import { IamStack } from '../lib/iam-stack';
import { SeedStack } from '../lib/seed-stack';
import { DashboardStack } from '../lib/dashboard-stack';

const app = new cdk.App();

const qualifier = app.node.tryGetContext('@aws-cdk/core:bootstrapQualifier') || 'hnb659fds';
const prefix = app.node.tryGetContext('prefix') || 'motoros';

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: app.node.tryGetContext('region') || process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

// Deployment dependency graph:
//
//   Layer 0 (parallel): VPC, Kinesis, SQS, S3, IAM, Alerting
//   Layer 1 (parallel): Aurora, ElastiCache  (depend on VPC)
//   Layer 2:            EKS (depends on VPC + SQS) — includes all pods
//
// Aurora restores from pre-seeded snapshot (-c auroraSnapshotId=...).
// No seed job needed — data comes pre-loaded.

// Layer 0 — no dependencies
const vpcStack = new VpcStack(app, `${prefix}-VPC`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS VPC and Networking',
});

const kinesisStack = new KinesisStack(app, `${prefix}-Kinesis`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS Kinesis Vehicle Telemetry Stream',
});

const sqsStack = new SqsStack(app, `${prefix}-SQS`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS SQS Queues for OTA and Firmware',
});

const s3Stack = new S3Stack(app, `${prefix}-S3`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS S3 Firmware Artifacts Bucket',
});

const iamStack = new IamStack(app, `${prefix}-IAM`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS IAM Roles and Policies for DevOps Agent',
});

const alertingStack = new AlertingStack(app, `${prefix}-Alerting`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS CloudWatch Alarms, SNS Alerts, and Dashboards',
  auroraClusterId: `${prefix}-db`,
  otaQueueName: sqsStack.otaQueue.queueName,
});
alertingStack.addDependency(sqsStack);

// Layer 1 — depend on VPC
const auroraStack = new AuroraStack(app, `${prefix}-Aurora`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS Aurora PostgreSQL Database',
  vpc: vpcStack.vpc,
});
auroraStack.addDependency(vpcStack);

const elastiCacheStack = new ElastiCacheStack(app, `${prefix}-ElastiCache`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS ElastiCache Redis Cluster',
  vpc: vpcStack.vpc,
});
elastiCacheStack.addDependency(vpcStack);

// Layer 2 — EKS with all microservices (needs Aurora + ElastiCache endpoints)
const eksStack = new EksStack(app, `${prefix}-EKS`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS EKS Cluster + Microservices',
  vpc: vpcStack.vpc,
  // Use deterministic Aurora endpoint name (avoids cross-stack ref to Aurora)
  dbHost: `${prefix}-db.cluster-placeholder.${env.region}.rds.amazonaws.com`,
  dbPort: '5432',
  dbName: 'motoros',
  dbUser: 'motoros_admin',
  dbPassword: 'WILL_BE_SET_BY_SEED_JOB',
  kinesisStream: `${prefix}-vehicle-telemetry`,
  sqsQueueUrl: sqsStack.otaQueue.queueUrl,
  redisHost: 'WILL_BE_SET_BY_SEED_JOB',
});
eksStack.addDependency(vpcStack);
eksStack.addDependency(sqsStack);

// DB seeding: Lambda Custom Resource seeds Aurora after creation
const seedStack = new SeedStack(app, `${prefix}-Seed`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS Database Seeding (Lambda)',
  vpc: vpcStack.vpc,
  dbSecretName: `${prefix}/db-credentials`,
});
seedStack.addDependency(auroraStack);

// Dashboard + Alert Receiver (depends on Alerting for SNS topic ARN)
const dashboardStack = new DashboardStack(app, `${prefix}-Dashboard`, {
  env, synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
  description: 'MotorOS Demo Dashboard + Alert Receiver',
  alertTopicArn: alertingStack.alertTopic.topicArn,
});
dashboardStack.addDependency(alertingStack);

// Tags
const commonTags: Record<string, string> = {
  env: 'production', app: 'motoros', team: 'platform',
  'cost-center': 'connected-vehicle', deployment: prefix,
  'auto-delete': 'no',
};
for (const [key, value] of Object.entries(commonTags)) {
  cdk.Tags.of(app).add(key, value);
}

app.synth();
