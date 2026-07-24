import * as cdk from 'aws-cdk-lib';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cw_actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';

export interface AlertingStackProps extends cdk.StackProps {
  auroraClusterId: string;
  otaQueueName: string;
}

export class AlertingStack extends cdk.Stack {
  public readonly alertTopic: sns.Topic;

  constructor(scope: Construct, id: string, props: AlertingStackProps) {
    super(scope, id, props);

    // Get context values for notification endpoints
    const pagerdutyKey = this.node.tryGetContext('pagerdutyIntegrationKey') || '';
    const slackWebhookUrl = this.node.tryGetContext('slackWebhookUrl') || '';
    const prefix = this.node.tryGetContext('prefix') || 'motoros';

    // SNS Topic for critical alerts
    this.alertTopic = new sns.Topic(this, 'CriticalAlertsTopic', {
      topicName: `${prefix}-critical-alerts`,
      displayName: 'MotorOS Critical Alerts',
    });

    // PagerDuty HTTPS subscription (if integration key provided)
    if (pagerdutyKey) {
      this.alertTopic.addSubscription(
        new subscriptions.UrlSubscription(
          `https://events.pagerduty.com/integration/${pagerdutyKey}/enqueue`,
          { protocol: sns.SubscriptionProtocol.HTTPS }
        )
      );
    }

    // Slack webhook subscription (if URL provided)
    if (slackWebhookUrl) {
      this.alertTopic.addSubscription(
        new subscriptions.UrlSubscription(slackWebhookUrl, {
          protocol: sns.SubscriptionProtocol.HTTPS,
        })
      );
    }

    // SNS Action for alarms
    const snsAction = new cw_actions.SnsAction(this.alertTopic);

    // =========================================================================
    // CloudWatch Alarms
    // =========================================================================

    // 1. Telemetry Ingestor Pod Restarts
    // Create a log group for pod restart monitoring
    const podLogGroup = new logs.LogGroup(this, 'PodRestartLogGroup', {
      logGroupName: `/${prefix}/kubernetes/pod-restarts`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Metric filter for pod restart events
    const podRestartMetricFilter = new logs.MetricFilter(this, 'PodRestartMetricFilter', {
      logGroup: podLogGroup,
      metricNamespace: 'MotorOS/Kubernetes',
      metricName: 'TelemetryIngestorPodRestarts',
      filterPattern: logs.FilterPattern.literal('Back-off restarting failed container telemetry-ingestor'),
      metricValue: '1',
      defaultValue: 0,
    });

    const podRestartAlarm = new cloudwatch.Alarm(this, 'TelemetryIngestorPodRestartsAlarm', {
      alarmName: `${prefix}-telemetry-ingestor-pod-restarts`,
      alarmDescription: 'Pods in CrashLoopBackOff detected',
      metric: new cloudwatch.Metric({
        namespace: 'MotorOS/Kubernetes',
        metricName: 'CrashLoopBackOffPods',
        statistic: 'Maximum',
        period: cdk.Duration.seconds(60),
      }),
      threshold: 0,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    podRestartAlarm.addAlarmAction(snsAction);
    podRestartAlarm.addOkAction(snsAction);

    // Auto-trigger DevOps Agent investigation (only if webhook is configured)
    // The alarm-bridge Lambda must exist BEFORE this alarm is created.
    // On first deploy: alarm deploys without Lambda action.
    // On second deploy (after Dashboard stack creates the Lambda): alarm updates to include it.
    // This is acceptable — trainers run `cdk deploy --all` twice, or the Lambda action is added manually.
    

    // 2. Aurora Replica Lag
    const auroraReplicaLagAlarm = new cloudwatch.Alarm(this, 'AuroraReplicaLagAlarm', {
      alarmName: `${prefix}-aurora-replica-lag`,
      alarmDescription: 'Aurora PostgreSQL replica lag exceeds 30 seconds',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/RDS',
        metricName: 'AuroraReplicaLagMaximum',
        dimensionsMap: {
          DBClusterIdentifier: props.auroraClusterId,
        },
        statistic: 'Maximum',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 30000, // milliseconds
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.MISSING,
    });
    auroraReplicaLagAlarm.addAlarmAction(snsAction);
    auroraReplicaLagAlarm.addOkAction(snsAction);

    // 3. Dealer Order Service 5xx Rate
    const dealerOrder5xxAlarm = new cloudwatch.Alarm(this, 'DealerOrderSvc5xxRateAlarm', {
      alarmName: `${prefix}-dealer-order-svc-5xx-rate`,
      alarmDescription: 'Dealer order service 5xx error rate exceeds 5%',
      metric: new cloudwatch.Metric({
        namespace: 'MotorOS/Services',
        metricName: 'ErrorRate',
        dimensionsMap: {
          Service: 'dealer-order-svc',
          ErrorType: '5xx',
        },
        statistic: 'Average',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 5,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    dealerOrder5xxAlarm.addAlarmAction(snsAction);
    dealerOrder5xxAlarm.addOkAction(snsAction);

    // 4. OTA Campaign Queue Depth
    const otaQueueDepthAlarm = new cloudwatch.Alarm(this, 'OtaCampaignQueueDepthAlarm', {
      alarmName: `${prefix}-ota-campaign-queue-depth`,
      alarmDescription: 'OTA campaign queue depth exceeds 500 messages for 10 minutes',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/SQS',
        metricName: 'ApproximateNumberOfMessagesVisible',
        dimensionsMap: {
          QueueName: props.otaQueueName,
        },
        statistic: 'Average',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 500,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    otaQueueDepthAlarm.addAlarmAction(snsAction);
    otaQueueDepthAlarm.addOkAction(snsAction);

    // 5. Anomalous DTC Rate — fires when DTC event rate exceeds baseline
    // This alarm is intentionally vague: it says "DTC rate is high" but doesn't
    // indicate why. The DevOps Agent must investigate the dtc_events table,
    // correlate with vehicle_ecus and telemetry to find root cause.
    const dtcRateAlarm = new cloudwatch.Alarm(this, 'AnomalousDTCRateAlarm', {
      alarmName: `${prefix}-anomalous-dtc-rate`,
      alarmDescription: 'DTC event rate exceeded expected baseline — investigate dtc_events table for pattern',
      metric: new cloudwatch.Metric({
        namespace: 'MotorOS/VehicleHealth',
        metricName: 'ActiveDTCCount',
        statistic: 'Maximum',
        period: cdk.Duration.minutes(1),
      }),
      threshold: 8,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    dtcRateAlarm.addAlarmAction(snsAction);
    dtcRateAlarm.addOkAction(snsAction);

    // =========================================================================
    // CloudWatch Dashboards
    // =========================================================================

    // MotorOS-Overview Dashboard
    new cloudwatch.Dashboard(this, 'OverviewDashboard', {
      dashboardName: `${prefix}-Overview`,
      widgets: [
        [
          new cloudwatch.TextWidget({
            markdown: '# MotorOS Platform Overview',
            width: 24,
            height: 1,
          }),
        ],
        [
          new cloudwatch.AlarmStatusWidget({
            title: 'Critical Alarms',
            alarms: [
              podRestartAlarm,
              auroraReplicaLagAlarm,
              dealerOrder5xxAlarm,
              otaQueueDepthAlarm,
            ],
            width: 24,
            height: 4,
          }),
        ],
        [
          new cloudwatch.GraphWidget({
            title: 'Kinesis - Vehicle Telemetry Throughput',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/Kinesis',
                metricName: 'IncomingRecords',
                dimensionsMap: { StreamName: `${prefix}-vehicle-telemetry` },
                statistic: 'Sum',
                period: cdk.Duration.minutes(1),
              }),
            ],
            width: 12,
            height: 6,
          }),
          new cloudwatch.GraphWidget({
            title: 'EKS Node CPU Utilization',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/EC2',
                metricName: 'CPUUtilization',
                statistic: 'Average',
                period: cdk.Duration.minutes(5),
              }),
            ],
            width: 12,
            height: 6,
          }),
        ],
      ],
    });

    // MotorOS-OTA Dashboard
    new cloudwatch.Dashboard(this, 'OTADashboard', {
      dashboardName: `${prefix}-OTA`,
      widgets: [
        [
          new cloudwatch.TextWidget({
            markdown: '# MotorOS OTA Campaign Monitoring',
            width: 24,
            height: 1,
          }),
        ],
        [
          new cloudwatch.GraphWidget({
            title: 'OTA Queue - Messages Visible',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/SQS',
                metricName: 'ApproximateNumberOfMessagesVisible',
                dimensionsMap: { QueueName: props.otaQueueName },
                statistic: 'Average',
                period: cdk.Duration.minutes(1),
              }),
            ],
            width: 12,
            height: 6,
          }),
          new cloudwatch.GraphWidget({
            title: 'OTA Queue - Messages Sent/Received',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/SQS',
                metricName: 'NumberOfMessagesSent',
                dimensionsMap: { QueueName: props.otaQueueName },
                statistic: 'Sum',
                period: cdk.Duration.minutes(1),
              }),
              new cloudwatch.Metric({
                namespace: 'AWS/SQS',
                metricName: 'NumberOfMessagesReceived',
                dimensionsMap: { QueueName: props.otaQueueName },
                statistic: 'Sum',
                period: cdk.Duration.minutes(1),
              }),
            ],
            width: 12,
            height: 6,
          }),
        ],
        [
          new cloudwatch.GraphWidget({
            title: 'OTA DLQ - Messages',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/SQS',
                metricName: 'ApproximateNumberOfMessagesVisible',
                dimensionsMap: { QueueName: `${prefix}-ota-campaign-jobs-dlq` },
                statistic: 'Average',
                period: cdk.Duration.minutes(1),
              }),
            ],
            width: 12,
            height: 6,
          }),
          new cloudwatch.GraphWidget({
            title: 'Firmware Distribution Queue',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/SQS',
                metricName: 'ApproximateNumberOfMessagesVisible',
                dimensionsMap: { QueueName: `${prefix}-firmware-distribution` },
                statistic: 'Average',
                period: cdk.Duration.minutes(1),
              }),
            ],
            width: 12,
            height: 6,
          }),
        ],
      ],
    });

    // MotorOS-Database Dashboard
    new cloudwatch.Dashboard(this, 'DatabaseDashboard', {
      dashboardName: `${prefix}-Database`,
      widgets: [
        [
          new cloudwatch.TextWidget({
            markdown: '# MotorOS Database Monitoring',
            width: 24,
            height: 1,
          }),
        ],
        [
          new cloudwatch.GraphWidget({
            title: 'Aurora - CPU Utilization',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/RDS',
                metricName: 'CPUUtilization',
                dimensionsMap: { DBClusterIdentifier: props.auroraClusterId },
                statistic: 'Average',
                period: cdk.Duration.minutes(1),
              }),
            ],
            width: 12,
            height: 6,
          }),
          new cloudwatch.GraphWidget({
            title: 'Aurora - Replica Lag',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/RDS',
                metricName: 'AuroraReplicaLagMaximum',
                dimensionsMap: { DBClusterIdentifier: props.auroraClusterId },
                statistic: 'Maximum',
                period: cdk.Duration.minutes(1),
              }),
            ],
            width: 12,
            height: 6,
          }),
        ],
        [
          new cloudwatch.GraphWidget({
            title: 'Aurora - Database Connections',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/RDS',
                metricName: 'DatabaseConnections',
                dimensionsMap: { DBClusterIdentifier: props.auroraClusterId },
                statistic: 'Sum',
                period: cdk.Duration.minutes(1),
              }),
            ],
            width: 12,
            height: 6,
          }),
          new cloudwatch.GraphWidget({
            title: 'Aurora - Freeable Memory',
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/RDS',
                metricName: 'FreeableMemory',
                dimensionsMap: { DBClusterIdentifier: props.auroraClusterId },
                statistic: 'Average',
                period: cdk.Duration.minutes(5),
              }),
            ],
            width: 12,
            height: 6,
          }),
        ],
      ],
    });

    // Outputs
    new cdk.CfnOutput(this, 'AlertTopicArn', {
      value: this.alertTopic.topicArn,
      description: 'SNS topic ARN for critical alerts',
    });
  }
}
