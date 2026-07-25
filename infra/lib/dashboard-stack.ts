import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as path from 'path';
import { Construct } from 'constructs';

export interface DashboardStackProps extends cdk.StackProps {
  alertTopicArn: string;
}

export class DashboardStack extends cdk.Stack {
  public readonly dashboardUrl: string;
  public readonly alertUrl: string;
  public readonly alarmBridgeFn: lambda.Function;

  constructor(scope: Construct, id: string, props: DashboardStackProps) {
    super(scope, id, props);

    const prefix = this.node.tryGetContext('prefix') || 'motoros';
    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;

    // Lambda role with read access to CloudWatch, SQS, Kinesis, RDS + logs
    const lambdaRole = new iam.Role(this, 'LambdaRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchFullAccess'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonKinesisReadOnlyAccess'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonRDSReadOnlyAccess'),
      ],
    });

    // Platform UI Lambda (GET /status)
    const platformUiFn = new lambda.Function(this, 'PlatformUi', {
      functionName: `${prefix}-platform-ui`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      timeout: cdk.Duration.seconds(15),
      memorySize: 256,
      role: lambdaRole,
      environment: { ACCOUNT: account, PREFIX: prefix },
      code: lambda.Code.fromAsset(path.join(__dirname, '../../dashboard/platform-ui')),
    });

    // Webhook receiver Lambda (GET /alert = dashboard, POST /alert = receive SNS)
    const webhookFn = new lambda.Function(this, 'WebhookReceiver', {
      functionName: `${prefix}-webhook-receiver`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
      role: lambdaRole,
      code: lambda.Code.fromAsset(path.join(__dirname, '../../dashboard/webhook-receiver')),
    });

    // Alarm Bridge — auto-triggers DevOps Agent investigation on alarm
    // CloudWatch Alarm → this Lambda → HMAC webhook → DevOps Agent
    const alarmBridgeRole = new iam.Role(this, 'AlarmBridgeRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // Create webhook secret from CDK context params (if provided)
    const webhookUrl = this.node.tryGetContext('devopsAgentWebhookUrl') || '';
    const webhookSecret = this.node.tryGetContext('devopsAgentWebhookSecret') || '';

    if (webhookUrl && webhookSecret) {
      new secretsmanager.Secret(this, 'WebhookSecret', {
        secretName: `${prefix}/devops-agent-webhook`,
        secretStringValue: cdk.SecretValue.unsafePlainText(
          JSON.stringify({ url: webhookUrl, secret: webhookSecret })
        ),
        description: 'DevOps Agent webhook URL and HMAC secret for auto-trigger',
      });
    }

    // Grant access to the webhook secret
    alarmBridgeRole.addToPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [`arn:aws:secretsmanager:${region}:${account}:secret:${prefix}/devops-agent-webhook*`],
    }));

    this.alarmBridgeFn = new lambda.Function(this, 'AlarmBridge', {
      functionName: `${prefix}-alarm-bridge`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.lambda_handler',
      timeout: cdk.Duration.seconds(30),
      memorySize: 128,
      role: alarmBridgeRole,
      environment: { WEBHOOK_SECRET_NAME: `${prefix}/devops-agent-webhook` },
      code: lambda.Code.fromAsset(path.join(__dirname, '../../dashboard/alarm-bridge')),
    });

    // Allow CloudWatch alarms to invoke this Lambda
    this.alarmBridgeFn.addPermission('CloudWatchInvoke', {
      principal: new iam.ServicePrincipal('lambda.alarms.cloudwatch.amazonaws.com'),
    });

    // Subscribe alarm-bridge to SNS so alarms trigger DevOps Agent investigation
    const alertTopic = sns.Topic.fromTopicArn(this, 'AlertTopic', props.alertTopicArn);
    alertTopic.addSubscription(new subscriptions.LambdaSubscription(webhookFn));
    alertTopic.addSubscription(new subscriptions.LambdaSubscription(this.alarmBridgeFn));

    // API Gateway
    const api = new apigateway.RestApi(this, 'DemoApi', {
      restApiName: `${prefix}-demo-dashboard`,
      description: 'MotorOS demo dashboard and alert receiver',
    });

    // /status → Platform UI
    const statusResource = api.root.addResource('status');
    statusResource.addMethod('GET', new apigateway.LambdaIntegration(platformUiFn));

    // /alert → Webhook receiver (GET = dashboard, POST = receive alerts)
    const alertResource = api.root.addResource('alert');
    alertResource.addMethod('GET', new apigateway.LambdaIntegration(webhookFn));
    alertResource.addMethod('POST', new apigateway.LambdaIntegration(webhookFn));

    // /alert/clear → Clear alarms
    const clearResource = alertResource.addResource('clear');
    clearResource.addMethod('POST', new apigateway.LambdaIntegration(webhookFn));

    // Wire alarm-bridge to the pod restart alarm
    // The Dashboard stack outputs the Lambda ARN — on second deploy or manual wiring,
    // the alarm action is added. For now, output instructions.
    

    // Outputs
    this.dashboardUrl = api.url + 'status';
    this.alertUrl = api.url + 'alert';

    new cdk.CfnOutput(this, 'PlatformDashboardUrl', { value: this.dashboardUrl });
    new cdk.CfnOutput(this, 'AlertFeedUrl', { value: this.alertUrl });
    new cdk.CfnOutput(this, 'AlarmBridgeFnArn', { value: this.alarmBridgeFn.functionArn });
  }
}
