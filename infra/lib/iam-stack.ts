import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export class IamStack extends cdk.Stack {
  public readonly devopsAgentRole: iam.Role;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // DevOps Agent Role
    this.devopsAgentRole = new iam.Role(this, 'DevOpsAgentRole', {
      roleName: `${this.node.tryGetContext('prefix') || 'motoros'}-devops-agent-${this.region}`,
      description: 'IAM role for MotorOS DevOps Agent with read-only access to infrastructure resources',
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal('lambda.amazonaws.com'),
        new iam.AccountRootPrincipal(),
      ),
      maxSessionDuration: cdk.Duration.hours(4),
    });

    // EKS read-only access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'EKSReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'eks:DescribeCluster',
        'eks:ListClusters',
        'eks:ListNodegroups',
        'eks:DescribeNodegroup',
        'eks:ListFargateProfiles',
        'eks:DescribeFargateProfile',
        'eks:ListUpdates',
        'eks:DescribeUpdate',
        'eks:AccessKubernetesApi',
      ],
      resources: ['*'],
    }));

    // RDS read-only access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'RDSReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'rds:DescribeDBClusters',
        'rds:DescribeDBInstances',
        'rds:DescribeDBClusterEndpoints',
        'rds:DescribeEvents',
        'rds:DescribeDBLogFiles',
        'rds:DownloadDBLogFilePortion',
        'rds:ListTagsForResource',
      ],
      resources: ['*'],
    }));

    // RDS Data API and Secrets Manager access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'RDSDataAPIAndSecrets',
      effect: iam.Effect.ALLOW,
      actions: [
        'rds-data:ExecuteStatement',
        'rds-data:BatchExecuteStatement',
        'secretsmanager:GetSecretValue',
        'secretsmanager:DescribeSecret',
        'secretsmanager:ListSecrets',
      ],
      resources: ['*'],
    }));

    // CloudWatch read-only access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'CloudWatchReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'cloudwatch:DescribeAlarms',
        'cloudwatch:GetMetricData',
        'cloudwatch:GetMetricStatistics',
        'cloudwatch:ListMetrics',
        'cloudwatch:GetDashboard',
        'cloudwatch:ListDashboards',
        'logs:GetLogEvents',
        'logs:FilterLogEvents',
        'logs:DescribeLogGroups',
        'logs:DescribeLogStreams',
        'logs:GetLogGroupFields',
        'logs:GetQueryResults',
        'logs:StartQuery',
        'logs:StopQuery',
      ],
      resources: ['*'],
    }));

    // Kinesis read-only access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'KinesisReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'kinesis:DescribeStream',
        'kinesis:DescribeStreamSummary',
        'kinesis:ListStreams',
        'kinesis:ListShards',
        'kinesis:GetShardIterator',
        'kinesis:GetRecords',
        'kinesis:ListTagsForStream',
      ],
      resources: ['*'],
    }));

    // SQS read-only access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'SQSReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'sqs:GetQueueAttributes',
        'sqs:GetQueueUrl',
        'sqs:ListQueues',
        'sqs:ListQueueTags',
        'sqs:ListDeadLetterSourceQueues',
      ],
      resources: ['*'],
    }));

    // EC2 read-only access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'EC2ReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'ec2:DescribeInstances',
        'ec2:DescribeSecurityGroups',
        'ec2:DescribeSubnets',
        'ec2:DescribeVpcs',
        'ec2:DescribeNetworkInterfaces',
        'ec2:DescribeVolumes',
        'ec2:DescribeInstanceStatus',
      ],
      resources: ['*'],
    }));

    // SSM read-only access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'SSMReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'ssm:GetParameter',
        'ssm:GetParameters',
        'ssm:GetParametersByPath',
        'ssm:DescribeParameters',
        'ssm:DescribeInstanceInformation',
        'ssm:ListCommands',
        'ssm:ListCommandInvocations',
      ],
      resources: ['*'],
    }));

    // S3 read-only access
    this.devopsAgentRole.addToPolicy(new iam.PolicyStatement({
      sid: 'S3ReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        's3:GetObject',
        's3:ListBucket',
        's3:GetBucketLocation',
        's3:GetBucketVersioning',
        's3:ListAllMyBuckets',
        's3:GetBucketTagging',
      ],
      resources: ['*'],
    }));

    // Outputs
    new cdk.CfnOutput(this, 'DevOpsAgentRoleArn', {
      value: this.devopsAgentRole.roleArn,
      description: 'ARN of the DevOps Agent IAM role',
      exportName: `${this.node.tryGetContext('prefix') || 'motoros'}-DevOpsAgentRoleArn`,
    });

    new cdk.CfnOutput(this, 'DevOpsAgentRoleName', {
      value: this.devopsAgentRole.roleName,
      description: 'Name of the DevOps Agent IAM role',
      exportName: `${this.node.tryGetContext('prefix') || 'motoros'}-DevOpsAgentRoleName`,
    });
  }
}
