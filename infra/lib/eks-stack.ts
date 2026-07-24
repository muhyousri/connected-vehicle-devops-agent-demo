import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as eks from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as path from 'path';
import * as fs from 'fs';
import { Construct } from 'constructs';

export interface EksStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  dbHost?: string;
  dbPort?: string;
  dbName?: string;
  dbUser?: string;
  dbPassword?: string;
  kinesisStream?: string;
  sqsQueueUrl?: string;
  redisHost?: string;
}

export class EksStack extends cdk.Stack {
  public readonly cluster: eks.Cluster;
  public readonly clusterSecurityGroup: ec2.ISecurityGroup;
  public readonly nodeGroupRole: iam.IRole;
  public readonly nsProdManifest: eks.KubernetesManifest;
  public readonly configProdManifest: eks.KubernetesManifest;

  constructor(scope: Construct, id: string, props: EksStackProps) {
    super(scope, id, props);

    const prefix = this.node.tryGetContext('prefix') || 'motoros';
    const clusterName = `${prefix}-cluster`;

    // 1. EKS ACCESS: Map deploying IAM role so users can kubectl directly
    const clusterAdminRole = new iam.Role(this, 'ClusterAdminRole', {
      roleName: `${clusterName}-admin-${cdk.Stack.of(this).region}`,
      assumedBy: new iam.AccountRootPrincipal(),
    });

    this.cluster = new eks.Cluster(this, 'Cluster', {
      clusterName,
      version: eks.KubernetesVersion.of('1.31'),
      vpc: props.vpc,
      defaultCapacity: 0,
      mastersRole: clusterAdminRole,
      vpcSubnets: [{ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }],
      endpointAccess: eks.EndpointAccess.PUBLIC_AND_PRIVATE,
      clusterLogging: [
        eks.ClusterLoggingTypes.API,
        eks.ClusterLoggingTypes.AUTHENTICATOR,
        eks.ClusterLoggingTypes.SCHEDULER,
      ],
    });

    // Map deployer role so trainers can kubectl without assuming cluster-admin
    const deployerRoleName = this.node.tryGetContext('deployerRoleName') || 'Admin';
    const adminRole = iam.Role.fromRoleName(this, 'DeployerRole', deployerRoleName);
    this.cluster.awsAuth.addRoleMapping(adminRole, {
      groups: ['system:masters'],
      username: 'admin-deployer',
    });

    // Map DevOps Agent roles so the agent can access pods/logs
    // Pass role ARNs via CDK context: -c devopsAgentRoleArns="arn1,arn2"
    const agentRoleArnsParam = this.node.tryGetContext('devopsAgentRoleArns') || '';
    if (agentRoleArnsParam) {
      const arns = agentRoleArnsParam.split(',').map((a: string) => a.trim()).filter((a: string) => a);
      arns.forEach((arn: string, i: number) => {
        const role = iam.Role.fromRoleArn(this, `AgentRole${i}`, arn, { mutable: false });
        this.cluster.awsAuth.addRoleMapping(role, {
          groups: ['system:masters'],
          username: `devops-agent-${i}`,
        });
      });
    }

    // Node group
    const nodeGroup = this.cluster.addNodegroupCapacity('NodeGroup', {
      nodegroupName: `${clusterName}-nodes`,
      instanceTypes: [new ec2.InstanceType('t3.medium')],
      minSize: 3,
      maxSize: 3,
      desiredSize: 3,
      diskSize: 50,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });

    this.clusterSecurityGroup = this.cluster.clusterSecurityGroup;
    this.nodeGroupRole = nodeGroup.role;

    // Grant node group access to Secrets Manager (needed by seed job running on nodes)
    this.nodeGroupRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('SecretsManagerReadWrite')
    );
    // Grant Kinesis access (needed by telemetry producer)
    this.nodeGroupRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonKinesisFullAccess')
    );
    // Grant CloudWatch access (needed by health-monitor to push metrics)
    this.nodeGroupRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchFullAccess')
    );

    // Container Insights addon for pod-level metrics
    new eks.CfnAddon(this, 'ContainerInsights', {
      clusterName: this.cluster.clusterName,
      addonName: 'amazon-cloudwatch-observability',
      resolveConflicts: 'OVERWRITE',
    });

    // 2. NAMESPACES
    const nsProd = this.cluster.addManifest('NsProd', {
      apiVersion: 'v1',
      kind: 'Namespace',
      metadata: { name: 'motoros-prod', labels: { app: 'motoros', env: 'production' } },
    });
    this.nsProdManifest = nsProd;

    const nsPlatform = this.cluster.addManifest('NsPlatform', {
      apiVersion: 'v1',
      kind: 'Namespace',
      metadata: { name: 'motoros-platform', labels: { app: 'motoros', env: 'production' } },
    });

    // 3. POD DEPLOYMENT: ConfigMaps + Deployments + Services
    const dbHost = props.dbHost || 'pending';
    const dbPort = props.dbPort || '5432';
    const dbName = props.dbName || 'motoros';
    const dbUser = props.dbUser || 'motoros_admin';
    const dbPassword = props.dbPassword || 'pending';
    const kinesisStream = props.kinesisStream || `${prefix}-vehicle-telemetry`;
    const sqsQueueUrl = props.sqsQueueUrl || 'pending';
    const redisHost = props.redisHost || 'pending';

    // Shared config for both namespaces
    const configData = {
      DB_HOST: dbHost, DB_PORT: dbPort, DB_NAME: dbName,
      DB_USER: dbUser, DB_PASSWORD: dbPassword,
      KINESIS_STREAM: kinesisStream, SQS_QUEUE_URL: sqsQueueUrl,
      REDIS_HOST: redisHost, AWS_DEFAULT_REGION: cdk.Stack.of(this).region,
    };

    const configProd = this.cluster.addManifest('ConfigProd', {
      apiVersion: 'v1', kind: 'ConfigMap',
      metadata: { name: 'motoros-config', namespace: 'motoros-prod' },
      data: configData,
    });
    configProd.node.addDependency(nsProd);
    this.configProdManifest = configProd;

    const configPlatform = this.cluster.addManifest('ConfigPlatform', {
      apiVersion: 'v1', kind: 'ConfigMap',
      metadata: { name: 'motoros-config', namespace: 'motoros-platform' },
      data: configData,
    });
    configPlatform.node.addDependency(nsPlatform);

    // Requirements
    const requirements = 'fastapi==0.109.0\nuvicorn==0.27.0\nboto3==1.34.0\npsycopg2-binary==2.9.9\nstructlog==24.1.0\n';
    const reqProd = this.cluster.addManifest('ReqProd', {
      apiVersion: 'v1', kind: 'ConfigMap',
      metadata: { name: 'motoros-requirements', namespace: 'motoros-prod' },
      data: { 'requirements.txt': requirements },
    });
    reqProd.node.addDependency(nsProd);

    const reqPlatform = this.cluster.addManifest('ReqPlatform', {
      apiVersion: 'v1', kind: 'ConfigMap',
      metadata: { name: 'motoros-requirements', namespace: 'motoros-platform' },
      data: { 'requirements.txt': requirements },
    });
    reqPlatform.node.addDependency(nsPlatform);

    // Entrypoint script that resolves DB credentials from Secrets Manager
    const resolveCredsScript = `
import os, json
try:
    import boto3
    pw = os.getenv('DB_PASSWORD', '')
    if not pw or pw in ('pending', 'WILL_BE_SET_BY_SEED_JOB', 'from-secret'):
        region = os.getenv('AWS_DEFAULT_REGION', 'eu-north-1')
        secret_name = '${prefix}/db-credentials'
        sm = boto3.client('secretsmanager', region_name=region)
        s = json.loads(sm.get_secret_value(SecretId=secret_name)['SecretString'])
        with open('/tmp/db_env', 'w') as f:
            f.write(f"export DB_HOST={s['host']}\\nexport DB_PORT={s['port']}\\nexport DB_USER={s['username']}\\nexport DB_PASSWORD={s['password']}\\n")
        print(f"[creds] Resolved from Secrets Manager: host={s['host']}")
    else:
        print("[creds] Using env var credentials")
except Exception as e:
    print(f"[creds] Warning: {e} - using env var fallback")
`;

    const entrypointProd = this.cluster.addManifest('EntrypointProd', {
      apiVersion: 'v1', kind: 'ConfigMap',
      metadata: { name: 'motoros-entrypoint', namespace: 'motoros-prod' },
      data: { 'resolve_creds.py': resolveCredsScript },
    });
    entrypointProd.node.addDependency(nsProd);

    const entrypointPlatform = this.cluster.addManifest('EntrypointPlatform', {
      apiVersion: 'v1', kind: 'ConfigMap',
      metadata: { name: 'motoros-entrypoint', namespace: 'motoros-platform' },
      data: { 'resolve_creds.py': resolveCredsScript },
    });
    entrypointPlatform.node.addDependency(nsPlatform);

    // Load service code from files and deploy
    const servicesDir = path.join(__dirname, '../../services');

    const prodServices = [
      { name: 'telemetry-ingestor', replicas: 2, team: 'vehicle-data', tier: 'critical' },
      { name: 'telemetry-processor', replicas: 1, team: 'vehicle-data', tier: 'standard' },
      { name: 'vehicle-state-svc', replicas: 1, team: 'vehicle-data', tier: 'standard' },
      { name: 'fleet-registry-svc', replicas: 1, team: 'fleet-ops', tier: 'standard' },
      { name: 'dealer-order-svc', replicas: 1, team: 'fleet-ops', tier: 'standard' },
      { name: 'warranty-claims-svc', replicas: 1, team: 'fleet-ops', tier: 'standard' },
      { name: 'ota-campaign-svc', replicas: 1, team: 'ota-platform', tier: 'critical' },
      { name: 'firmware-distribution-svc', replicas: 2, team: 'ota-platform', tier: 'critical' },
    ];

    const platformServices = [
      { name: 'auth-svc', replicas: 1, team: 'platform-core', tier: 'critical' },
      { name: 'notification-svc', replicas: 1, team: 'platform-core', tier: 'standard' },
      { name: 'audit-log-svc', replicas: 1, team: 'platform-core', tier: 'standard' },
      { name: 'api-gateway-svc', replicas: 1, team: 'platform-core', tier: 'critical' },
    ];

    const deployService = (
      svc: { name: string; replicas: number; team: string; tier: string },
      namespace: string,
      deps: any[],
    ) => {
      // Read the service code at synth time
      const codePath = path.join(servicesDir, svc.name, 'main.py');
      const code = fs.existsSync(codePath) ? fs.readFileSync(codePath, 'utf-8') : '# placeholder';

      const codeMap = this.cluster.addManifest(`Code-${svc.name}`, {
        apiVersion: 'v1', kind: 'ConfigMap',
        metadata: { name: `${svc.name}-code`, namespace },
        data: { 'main.py': code },
      });

      const deploy = this.cluster.addManifest(`Deploy-${svc.name}`,
        {
          apiVersion: 'apps/v1', kind: 'Deployment',
          metadata: {
            name: svc.name, namespace,
            labels: { app: svc.name, version: 'v2.4.1', team: svc.team, 'service-tier': svc.tier },
            annotations: { 'prometheus.io/scrape': 'true', 'prometheus.io/port': '8080' },
          },
          spec: {
            replicas: svc.replicas,
            selector: { matchLabels: { app: svc.name } },
            template: {
              metadata: { labels: { app: svc.name, version: 'v2.4.1', team: svc.team } },
              spec: {
                containers: [{
                  name: svc.name,
                  image: 'python:3.11-slim',
                  command: ['/bin/sh', '-c'],
                  args: ['pip install --no-cache-dir -r /requirements/requirements.txt -q && cd /app && python3 /entrypoint/resolve_creds.py && . /tmp/db_env 2>/dev/null; cd /app && uvicorn main:app --host 0.0.0.0 --port 8080'],
                  ports: [{ containerPort: 8080 }],
                  envFrom: [{ configMapRef: { name: 'motoros-config' } }],
                  env: [{ name: 'SERVICE_NAME', value: svc.name }, { name: 'SECRETS_PREFIX', value: prefix }],
                  resources: { requests: { cpu: '100m', memory: '128Mi' }, limits: { cpu: '250m', memory: '256Mi' } },
                  livenessProbe: { httpGet: { path: '/health', port: 8080 }, initialDelaySeconds: 60, periodSeconds: 10 },
                  readinessProbe: { httpGet: { path: '/ready', port: 8080 }, initialDelaySeconds: 40, periodSeconds: 5 },
                  volumeMounts: [
                    { name: 'code', mountPath: '/app' },
                    { name: 'requirements', mountPath: '/requirements' },
                    { name: 'entrypoint', mountPath: '/entrypoint' },
                  ],
                }],
                volumes: [
                  { name: 'code', configMap: { name: `${svc.name}-code` } },
                  { name: 'requirements', configMap: { name: 'motoros-requirements' } },
                  { name: 'entrypoint', configMap: { name: 'motoros-entrypoint' } },
                ],
              },
            },
          },
        },
        {
          apiVersion: 'v1', kind: 'Service',
          metadata: { name: svc.name, namespace, labels: { app: svc.name } },
          spec: { type: 'ClusterIP', ports: [{ port: 80, targetPort: 8080 }], selector: { app: svc.name } },
        },
      );

      for (const dep of deps) { codeMap.node.addDependency(dep); deploy.node.addDependency(codeMap); }
    };

    for (const svc of prodServices) {
      deployService(svc, 'motoros-prod', [configProd, reqProd]);
    }
    for (const svc of platformServices) {
      deployService(svc, 'motoros-platform', [configPlatform, reqPlatform]);
    }

    // 4. TELEMETRY PRODUCER — feeds Kinesis stream with fake vehicle data
    const telemetryProducer = this.cluster.addManifest('TelemetryProducer', {
      apiVersion: 'apps/v1', kind: 'Deployment',
      metadata: { name: 'telemetry-producer', namespace: 'motoros-prod', labels: { app: 'telemetry-producer', team: 'vehicle-data' } },
      spec: {
        replicas: 1,
        selector: { matchLabels: { app: 'telemetry-producer' } },
        template: {
          metadata: { labels: { app: 'telemetry-producer', team: 'vehicle-data' } },
          spec: {
            containers: [{
              name: 'producer',
              image: 'python:3.11-slim',
              command: ['/bin/sh', '-c'],
              args: [`pip install -q boto3 2>/dev/null && python3 -u -c "
import boto3, json, random, time
from datetime import datetime, timezone
STREAM='${prefix}-vehicle-telemetry'
REGION='${cdk.Stack.of(this).region}'
VINS=['WBA8B9G34KG123404','WBS4Z9C59LA123410','5YJ3E1EA5LF123420','1FA6P8CF5L5123430','WDD2050751A123440','WBA3A5G59DNP26082','5YJ3E1EB7LF123450']
kinesis=boto3.client('kinesis',region_name=REGION)
print(f'Telemetry producer started: stream={STREAM}')
batch=0
while True:
    batch+=1
    records=[]
    for _ in range(random.randint(5,15)):
        vin=random.choice(VINS)
        r={'vehicle_vin':vin,'timestamp':datetime.now(timezone.utc).isoformat(),'event_type':random.choice(['position','engine','fuel','diagnostic']),'latitude':round(random.uniform(25,48),6),'longitude':round(random.uniform(-125,-70),6),'speed_kmh':round(random.uniform(0,180),1),'fuel_level_pct':round(random.uniform(5,100),1),'engine_temp_c':round(random.uniform(80,110),1),'odometer_km':random.randint(1000,200000)}
        records.append({'Data':json.dumps(r).encode(),'PartitionKey':vin})
    try:
        resp=kinesis.put_records(StreamName=STREAM,Records=records)
        failed=resp.get("FailedRecordCount",0); print(f"[batch {batch}] Sent {len(records)} records, failed: {failed}")
    except Exception as e:
        print(f'[batch {batch}] Error: {e}')
    time.sleep(10)
"`],
              resources: { requests: { cpu: '50m', memory: '64Mi' }, limits: { cpu: '100m', memory: '128Mi' } },
            }],
          },
        },
      },
    });
    telemetryProducer.node.addDependency(nsProd);

    // 5. POSTGRES-MCP — MCP server connected to Aurora
    const pgMcpSecret = this.cluster.addManifest('PgMcpSecret', {
      apiVersion: 'v1', kind: 'Secret',
      metadata: { name: 'motoros-db-connection', namespace: 'motoros-platform' },
      type: 'Opaque',
      stringData: {
        'connection-string': `postgresql://${dbUser}:${dbPassword}@${dbHost}:5432/motoros`,
      },
    });
    pgMcpSecret.node.addDependency(nsPlatform);

    const pgMcp = this.cluster.addManifest('PostgresMcp',
      {
        apiVersion: 'apps/v1', kind: 'Deployment',
        metadata: { name: 'postgres-mcp', namespace: 'motoros-platform', labels: { app: 'postgres-mcp', component: 'mcp-server' } },
        spec: {
          replicas: 1,
          selector: { matchLabels: { app: 'postgres-mcp' } },
          template: {
            metadata: { labels: { app: 'postgres-mcp', component: 'mcp-server' } },
            spec: {
              containers: [{
                name: 'postgres-mcp',
                image: 'node:20-slim',
                command: ['/bin/sh', '-c'],
                args: ['npm install -g @modelcontextprotocol/server-postgres 2>/dev/null && echo "postgres-mcp ready" && sleep infinity'],
                env: [{ name: 'POSTGRES_CONNECTION_STRING', valueFrom: { secretKeyRef: { name: 'motoros-db-connection', key: 'connection-string' } } }],
                resources: { requests: { cpu: '50m', memory: '128Mi' }, limits: { cpu: '200m', memory: '256Mi' } },
              }],
            },
          },
        },
      },
      {
        apiVersion: 'v1', kind: 'Service',
        metadata: { name: 'postgres-mcp', namespace: 'motoros-platform', labels: { app: 'postgres-mcp' } },
        spec: { type: 'ClusterIP', ports: [{ port: 3000, targetPort: 3000 }], selector: { app: 'postgres-mcp' } },
      },
    );
    pgMcp.node.addDependency(pgMcpSecret);

    // 6. HEALTH MONITOR — pushes pod restart/OOM metrics to CloudWatch
    const healthMonitorRbac = this.cluster.addManifest('HealthMonitorRBAC',
      {
        apiVersion: 'rbac.authorization.k8s.io/v1', kind: 'ClusterRole',
        metadata: { name: 'pod-reader' },
        rules: [{ apiGroups: [''], resources: ['pods'], verbs: ['get', 'list', 'watch'] }],
      },
      {
        apiVersion: 'rbac.authorization.k8s.io/v1', kind: 'ClusterRoleBinding',
        metadata: { name: 'health-monitor-pod-reader' },
        roleRef: { apiGroup: 'rbac.authorization.k8s.io', kind: 'ClusterRole', name: 'pod-reader' },
        subjects: [{ kind: 'ServiceAccount', name: 'default', namespace: 'motoros-prod' }],
      },
    );
    healthMonitorRbac.node.addDependency(nsProd);

    const healthMonitor = this.cluster.addManifest('HealthMonitor', {
      apiVersion: 'apps/v1', kind: 'Deployment',
      metadata: { name: 'health-monitor', namespace: 'motoros-prod', labels: { app: 'health-monitor' } },
      spec: {
        replicas: 1,
        selector: { matchLabels: { app: 'health-monitor' } },
        template: {
          metadata: { labels: { app: 'health-monitor' } },
          spec: {
            containers: [{
              name: 'monitor',
              image: 'amazon/aws-cli:2.15.0',
              command: ['/bin/sh', '-c'],
              args: [`curl -sLO "https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl" && chmod +x kubectl && mv kubectl /usr/local/bin/ && REGION=${cdk.Stack.of(this).region} && CLUSTER_ARN=$(aws rds describe-db-clusters --db-cluster-identifier ${prefix}-db --region $REGION --query 'DBClusters[0].DBClusterArn' --output text 2>/dev/null || echo "") && SECRET_ARN=$(aws secretsmanager list-secrets --region $REGION --filters Key=name,Values=${prefix}/db-credentials --query 'SecretList[0].ARN' --output text 2>/dev/null || echo "") && echo "Health monitor started (cluster=$CLUSTER_ARN)" && while true; do CRASHLOOP=$(kubectl get pods -n motoros-prod -o json 2>/dev/null | grep -c '"reason": "CrashLoopBackOff"' || true); CRASHLOOP=\${CRASHLOOP:-0}; OOM=$(kubectl get pods -n motoros-prod -o json 2>/dev/null | grep -c '"reason": "OOMKilled"' || true); OOM=\${OOM:-0}; DTC_COUNT=0; if [ -n "$CLUSTER_ARN" ] && [ "$CLUSTER_ARN" != "None" ]; then DTC_COUNT=$(aws rds-data execute-statement --resource-arn "$CLUSTER_ARN" --secret-arn "$SECRET_ARN" --database motoros --sql "SELECT COUNT(*) as cnt FROM dtc_events WHERE status = 'ACTIVE' AND last_seen_at > NOW() - interval '1 hour'" --region $REGION --output json 2>/dev/null | grep -o '"longValue":[0-9]*' | grep -o '[0-9]*' || echo "0"); DTC_COUNT=\${DTC_COUNT:-0}; fi; aws cloudwatch put-metric-data --namespace "MotorOS/Kubernetes" --metric-data "[{\\"MetricName\\":\\"CrashLoopBackOffPods\\",\\"Value\\":$\{CRASHLOOP},\\"Unit\\":\\"Count\\"},{\\"MetricName\\":\\"OOMKilledPods\\",\\"Value\\":$\{OOM},\\"Unit\\":\\"Count\\"}]" --region $REGION 2>/dev/null; aws cloudwatch put-metric-data --namespace "MotorOS/VehicleHealth" --metric-data "[{\\"MetricName\\":\\"ActiveDTCCount\\",\\"Value\\":$\{DTC_COUNT},\\"Unit\\":\\"Count\\"}]" --region $REGION 2>/dev/null; echo "$(date -u +%H:%M:%S) crashloop=$CRASHLOOP oom=$OOM dtc_active=$DTC_COUNT"; sleep 30; done`],
              resources: { requests: { cpu: '50m', memory: '64Mi' }, limits: { cpu: '100m', memory: '128Mi' } },
            }],
          },
        },
      },
    });
    healthMonitor.node.addDependency(healthMonitorRbac);
    healthMonitor.node.addDependency(nsProd);

    // 7. DEVOPS AGENT — map agent roles to EKS for kubectl access
    // These roles are created by the DevOps Agent console (Agent Space setup)
    // Map them so the agent can describe pods, get logs, etc.
    const agentRoleMapping = this.cluster.addManifest('DevOpsAgentAuth',
      {
        apiVersion: 'rbac.authorization.k8s.io/v1', kind: 'ClusterRoleBinding',
        metadata: { name: 'devops-agent-admin' },
        roleRef: { apiGroup: 'rbac.authorization.k8s.io', kind: 'ClusterRole', name: 'cluster-admin' },
        subjects: [
          { kind: 'Group', name: 'devops-agent', apiGroup: 'rbac.authorization.k8s.io' },
        ],
      },
    );

    // Outputs
    new cdk.CfnOutput(this, 'ClusterEndpoint', { value: this.cluster.clusterEndpoint });
    new cdk.CfnOutput(this, 'ClusterName', { value: this.cluster.clusterName });
    new cdk.CfnOutput(this, 'KubectlRoleArn', { value: this.cluster.kubectlRole!.roleArn });
    new cdk.CfnOutput(this, 'ClusterAdminRoleArn', { value: clusterAdminRole.roleArn });
  }
}
