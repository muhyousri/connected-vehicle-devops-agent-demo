import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import { Construct } from 'constructs';

export interface AuroraStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
}

export class AuroraStack extends cdk.Stack {
  public readonly cluster: rds.DatabaseCluster;
  public readonly clusterEndpoint: string;
  public readonly dbSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: AuroraStackProps) {
    super(scope, id, props);

    const prefix = this.node.tryGetContext('prefix') || 'motoros';
    const snapshotId = this.node.tryGetContext('auroraSnapshotId') || '';

    this.dbSecurityGroup = new ec2.SecurityGroup(this, 'DbSg', {
      vpc: props.vpc,
      description: 'MotorOS Aurora PostgreSQL SG',
      allowAllOutbound: false,
    });

    this.dbSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(5432),
      'Allow PostgreSQL from within VPC'
    );

    // Build cluster props — conditionally restore from snapshot
    const clusterProps: rds.DatabaseClusterProps = {
      clusterIdentifier: `${prefix}-db`,
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.of('16.8', '16'),
      }),
      credentials: rds.Credentials.fromGeneratedSecret('motoros_admin', {
        secretName: `${prefix}/db-credentials`,
      }),
      defaultDatabaseName: 'motoros',
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [this.dbSecurityGroup],
      writer: rds.ClusterInstance.provisioned('Writer', {
        instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MEDIUM),
        enablePerformanceInsights: true,
      }),
      readers: [
        rds.ClusterInstance.provisioned('Reader1', {
          instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MEDIUM),
          enablePerformanceInsights: true,
        }),
      ],
      monitoringInterval: cdk.Duration.seconds(60),
      storageEncrypted: true,
      backup: { retention: cdk.Duration.days(7) },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    };

    this.cluster = new rds.DatabaseCluster(this, 'AuroraCluster', clusterProps);

    // If snapshot ID provided, set it on the CfnDBCluster (L1 override)
    if (snapshotId) {
      const cfnCluster = this.cluster.node.defaultChild as rds.CfnDBCluster;
      cfnCluster.snapshotIdentifier = snapshotId;
    }

    this.clusterEndpoint = this.cluster.clusterEndpoint.hostname;

    new cdk.CfnOutput(this, 'AuroraEndpoint', { value: this.cluster.clusterEndpoint.hostname });
    new cdk.CfnOutput(this, 'AuroraReaderEndpoint', { value: this.cluster.clusterReadEndpoint.hostname });
    new cdk.CfnOutput(this, 'AuroraSecretArn', { value: this.cluster.secret!.secretArn });
  }
}
