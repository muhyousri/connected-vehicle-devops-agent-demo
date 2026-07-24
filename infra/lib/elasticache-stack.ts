import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as elasticache from 'aws-cdk-lib/aws-elasticache';
import { Construct } from 'constructs';

export interface ElastiCacheStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
}

export class ElastiCacheStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ElastiCacheStackProps) {
    super(scope, id, props);

    const prefix = this.node.tryGetContext('prefix') || 'motoros';

    const redisSg = new ec2.SecurityGroup(this, 'RedisSg', {
      vpc: props.vpc,
      description: 'MotorOS Redis SG',
      allowAllOutbound: false,
    });

    redisSg.addIngressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(6379),
      'Allow Redis from within VPC'
    );

    const subnetGroup = new elasticache.CfnSubnetGroup(this, 'SubnetGroup', {
      cacheSubnetGroupName: `${prefix}-redis-subnets`,
      description: 'MotorOS Redis subnet group',
      subnetIds: props.vpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }).subnetIds,
    });

    const redis = new elasticache.CfnCacheCluster(this, 'Redis', {
      clusterName: `${prefix}-cache`,
      engine: 'redis',
      cacheNodeType: 'cache.t3.micro',
      numCacheNodes: 1,
      port: 6379,
      vpcSecurityGroupIds: [redisSg.securityGroupId],
      cacheSubnetGroupName: subnetGroup.cacheSubnetGroupName,
      engineVersion: '7.1',
    });
    redis.addDependency(subnetGroup);

    new cdk.CfnOutput(this, 'RedisEndpoint', { value: redis.attrRedisEndpointAddress });
  }
}
