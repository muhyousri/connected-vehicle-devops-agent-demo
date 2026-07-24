import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as path from 'path';
import * as fs from 'fs';
import { Construct } from 'constructs';

export interface SeedStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  dbSecretName: string;
}

export class SeedStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SeedStackProps) {
    super(scope, id, props);

    const prefix = this.node.tryGetContext('prefix') || 'motoros';

    // Read seed.sql
    const seedSqlPath = path.join(__dirname, '../../seed/seed.sql');
    const seedSql = fs.readFileSync(seedSqlPath, 'utf-8');

    // Lambda SG — Aurora already allows all VPC CIDR on 5432
    const lambdaSg = new ec2.SecurityGroup(this, 'SeedLambdaSg', {
      vpc: props.vpc,
      description: 'SG for DB seed Lambda',
    });

    // Seed Lambda — uses psycopg2 layer
    const seedFn = new lambda.Function(this, 'SeedFn', {
      functionName: `${prefix}-db-seed`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      timeout: cdk.Duration.minutes(5),
      memorySize: 256,
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSg],
      environment: {
        DB_SECRET_NAME: props.dbSecretName,
        DB_NAME: 'motoros',
      },
      code: lambda.Code.fromInline(`
import json, os, boto3, urllib.request

def handler(event, context):
    request_type = event.get('RequestType', 'Create')
    if request_type == 'Delete':
        return send_response(event, context, 'SUCCESS', {})

    try:
        # Get DB credentials
        sm = boto3.client('secretsmanager')
        secret = json.loads(sm.get_secret_value(SecretId=os.environ['DB_SECRET_NAME'])['SecretString'])

        # Connect and seed
        import psycopg2
        conn = psycopg2.connect(
            host=secret['host'], port=secret['port'],
            dbname=os.environ['DB_NAME'],
            user=secret['username'], password=secret['password'],
            connect_timeout=10
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(event['ResourceProperties']['SeedSql'])
        cur.close()
        conn.close()
        return send_response(event, context, 'SUCCESS', {'Message': 'DB seeded'})
    except Exception as e:
        print(f"Error: {e}")
        return send_response(event, context, 'FAILED', {'Error': str(e)})

def send_response(event, context, status, data):
    body = json.dumps({
        'Status': status,
        'Reason': data.get('Error', 'See CloudWatch'),
        'PhysicalResourceId': context.log_stream_name,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': data
    })
    req = urllib.request.Request(event['ResponseURL'], data=body.encode(), method='PUT')
    req.add_header('Content-Type', '')
    urllib.request.urlopen(req)
    return body
`),
    });

    // Grant Secrets Manager access
    seedFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [`arn:aws:secretsmanager:${this.region}:${this.account}:secret:${props.dbSecretName}*`],
    }));

    // Add psycopg2 as a layer (use community layer)
    // The inline code imports psycopg2 — we need a layer that provides it
    // Using the well-known psycopg2 layer for Python 3.12
    const psycopg2Layer = new lambda.LayerVersion(this, 'Psycopg2Layer', {
      code: lambda.Code.fromAsset(path.join(__dirname, '../../seed/lambda-layer')),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      description: 'psycopg2-binary for Python 3.12',
    });
    seedFn.addLayers(psycopg2Layer);

    // Custom Resource that triggers the seed on deploy
    new cdk.CustomResource(this, 'SeedTrigger', {
      serviceToken: seedFn.functionArn,
      properties: {
        SeedSql: seedSql,
        // Change this to force re-seed on updates
        Version: '1',
      },
    });

    // Grant Lambda invoke for CloudFormation custom resource
    seedFn.addPermission('CfnInvoke', {
      principal: new iam.ServicePrincipal('cloudformation.amazonaws.com'),
    });
  }
}
