import * as cdk from 'aws-cdk-lib';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import { Construct } from 'constructs';

export class SqsStack extends cdk.Stack {
  public readonly otaQueue: sqs.Queue;
  public readonly otaDlq: sqs.Queue;
  public readonly firmwareQueue: sqs.Queue;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const prefix = this.node.tryGetContext('prefix') || 'motoros';

    this.otaDlq = new sqs.Queue(this, 'OtaDlq', {
      queueName: `${prefix}-ota-campaign-jobs-dlq`,
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    this.otaQueue = new sqs.Queue(this, 'OtaQueue', {
      queueName: `${prefix}-ota-campaign-jobs`,
      visibilityTimeout: cdk.Duration.seconds(300),
      retentionPeriod: cdk.Duration.days(7),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      deadLetterQueue: { queue: this.otaDlq, maxReceiveCount: 3 },
    });

    this.firmwareQueue = new sqs.Queue(this, 'FirmwareQueue', {
      queueName: `${prefix}-firmware-distribution`,
      visibilityTimeout: cdk.Duration.seconds(300),
      retentionPeriod: cdk.Duration.days(7),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    new cloudwatch.Alarm(this, 'OtaQueueDepthAlarm', {
      alarmName: `${prefix}-ota-queue-depth-high`,
      alarmDescription: 'OTA campaign jobs queue depth exceeds 500 for 10 min',
      metric: this.otaQueue.metricApproximateNumberOfMessagesVisible({
        period: cdk.Duration.minutes(5),
        statistic: 'Average',
      }),
      threshold: 500,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    new cdk.CfnOutput(this, 'OtaQueueUrl', { value: this.otaQueue.queueUrl });
    new cdk.CfnOutput(this, 'FirmwareQueueUrl', { value: this.firmwareQueue.queueUrl });
  }
}
