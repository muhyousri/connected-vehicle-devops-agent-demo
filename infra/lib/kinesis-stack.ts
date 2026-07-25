import * as cdk from 'aws-cdk-lib';
import * as kinesis from 'aws-cdk-lib/aws-kinesis';
import { Construct } from 'constructs';

export class KinesisStack extends cdk.Stack {
  public readonly stream: kinesis.Stream;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const prefix = this.node.tryGetContext('prefix') || 'motoros';

    this.stream = new kinesis.Stream(this, 'TelemetryStream', {
      streamName: `${prefix}-vehicle-telemetry`,
      shardCount: 2,
      retentionPeriod: cdk.Duration.hours(24),
    });

    // Enable enhanced shard-level metrics so the agent can see per-shard throughput
    const cfnStream = this.stream.node.defaultChild as kinesis.CfnStream;
    cfnStream.addPropertyOverride('StreamModeDetails', { StreamMode: 'PROVISIONED' });
    cfnStream.addPropertyOverride('EnhancedMetrics', [{
      ShardLevelMetrics: [
        'IncomingBytes', 'IncomingRecords', 'OutgoingBytes', 'OutgoingRecords',
        'WriteProvisionedThroughputExceeded', 'ReadProvisionedThroughputExceeded',
        'IteratorAgeMilliseconds',
      ],
    }]);

    new cdk.CfnOutput(this, 'StreamArn', { value: this.stream.streamArn });
    new cdk.CfnOutput(this, 'StreamName', { value: this.stream.streamName });
  }
}
