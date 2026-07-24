import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export class S3Stack extends cdk.Stack {
  public readonly firmwareBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const prefix = this.node.tryGetContext('prefix') || 'motoros';

    this.firmwareBucket = new s3.Bucket(this, 'FirmwareBucket', {
      bucketName: `${prefix}-firmware-${cdk.Aws.ACCOUNT_ID}-${cdk.Aws.REGION}`,
      versioned: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        {
          id: 'MoveToIA',
          enabled: true,
          transitions: [
            { storageClass: s3.StorageClass.INFREQUENT_ACCESS, transitionAfter: cdk.Duration.days(30) },
          ],
        },
      ],
    });

    new cdk.CfnOutput(this, 'BucketName', { value: this.firmwareBucket.bucketName });
  }
}
