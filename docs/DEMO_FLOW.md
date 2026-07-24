# Suggested Demo Flow (45 Minutes)

## Overview

This document describes a recommended sequence for demonstrating AWS DevOps Agent capabilities using the MotorOS environment. Adjust timing and depth based on audience.

## Pre-Demo Checklist

- [ ] Infrastructure deployed and healthy (`kubectl get pods -n motoros-prod` shows 12 Running)
- [ ] DevOps Agent Space configured with webhook
- [ ] Platform dashboard open: `<Dashboard URL>/prod/status`
- [ ] Alert feed open: `<Dashboard URL>/prod/alert`
- [ ] DevOps Agent Web App open (Operator access)
- [ ] Terminal ready with `chaos/` directory

## Sequence

### Step 1: Environment Discovery (8 min)

**Goal:** Show the agent building a complete mental model of an unfamiliar system.

**Prompt:**
```
Describe the MotorOS platform. What services are running, what is the data flow, and what is the current health?
```

**Expected output:** Full architecture discovery including EKS workloads, Aurora cluster, Kinesis stream, SQS queues, CloudWatch alarms.

**Follow-up:**
```
Which services handle OTA firmware updates, and are they healthy?
```

**Talking point:** The agent discovered 12 microservices, a database with 7 tables, a streaming pipeline, and confirmed health. No pre-configuration. No runbooks.

---

### Step 2: Alerting (8 min)

**Goal:** Show the agent understanding and explaining the monitoring pipeline.

**Prompt:**
```
What alerting is configured for the MotorOS platform? Walk me through the full signal chain from a pod crash to a notification.
```

**Expected output:** Alarm definitions, SNS topic, subscription endpoints, routing path explanation.

**Talking point:** The agent understands the complete signal chain. In production, you would ask it to wire PagerDuty or Slack here.

---

### Step 3: Incident (12 min)

**Goal:** Demonstrate autonomous investigation and root cause analysis.

**Setup:** Run `./chaos/inject-incident.sh` from terminal. If auto-trigger is configured, the agent begins investigating immediately. If not, wait ~2 minutes for the dashboard to show degraded, then prompt manually.

**If auto-triggered:** Switch to the Web App. An investigation is already running.

**If manual, prompt:**
```
The MotorOS platform is degraded. What is happening?
```

**Follow-up (after agent identifies OOM):**
```
What is the root cause? Check the pod events and describe the failure.
```

**Expected output:** Agent identifies CrashLoopBackOff, OOMKilled, traces to memory limit under traffic load, provides remediation steps.

**Talking point:** The agent correlated pod events, Kubernetes state, and CloudWatch metrics into a single root cause. What takes an engineer 15 minutes of console-switching took 30 seconds.

**Reset:** Run `./chaos/reset-incident.sh` when ready.

---

### Step 4: Custom Skill — Fleet Impact Assessment (7 min)

**Goal:** Show how Skills encode domain knowledge the agent uses automatically.

**Setup:** Ensure the `vehicle-fleet-impact-assessment` skill is active in the Agent Space. Inject the incident again if the system is currently healthy.

**Prompt:**
```
What is the customer impact of this incident? How many vehicles and fleets are affected?
```

**Expected output:** Structured impact report with severity classification, vehicle counts, fleet breakdown, campaign status, recommended actions.

**Talking point:** Skills encode your senior engineers' domain knowledge. Written once as a markdown file. Available to every operator, every shift, automatically.

---

### Step 5: Production Readiness Review (8 min)

**Goal:** Show proactive evaluation that finds real issues.

**Setup:** Reset the incident first (`./chaos/reset-incident.sh`).

**Prompt:**
```
Run a production readiness evaluation on the MotorOS platform. Check for resilience, security, and operational gaps.
```

**Expected output:** The agent identifies real findings: missing encryption, insufficient memory headroom, missing pod disruption budgets, single NAT gateway.

**Talking point:** The agent found real issues in 30 seconds. The OOM problem from Step 3 appears here as a recommendation, connecting the reactive and proactive stories.

---

### Closing (2 min)

Recap: discovery, alerting, incident response, domain skills, proactive prevention.

Single command deploys. Single command destroys. All standard AWS services.

---

## Timing Variants

| Duration | Modules |
|----------|---------|
| 30 min | Steps 1, 3, 4 |
| 45 min | Steps 1 through 5 |
| 60 min | All steps + formal investigation + autonomous trigger walkthrough |

## Reset Between Runs

```bash
cd chaos && ./reset-incident.sh
```

Dashboard returns to green within 2 minutes.
