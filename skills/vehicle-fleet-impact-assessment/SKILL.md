---
name: vehicle-fleet-impact-assessment
description: Assess the customer and vehicle fleet impact of an active platform 
  incident. Use this skill when MotorOS platform services are degraded and you need 
  to quantify how many vehicles, fleets, and customers are affected. This skill 
  translates infrastructure failures into business impact statements suitable for 
  incident commanders, customer communications, and executive escalation.
---

# Vehicle Fleet Impact Assessment

Use this skill when an incident is active on the MotorOS platform and stakeholders 
need to understand the **customer impact** — not just the infrastructure state.

## DB Connectivity

All queries target the MotorOS Aurora cluster:
- **Cluster**: `motoros3-db`
- **Database**: `motoros`
- **Credentials**: Secrets Manager at `motoros3/db-credentials`

Use the RDS Data API (`rds-data:ExecuteStatement`) with the cluster ARN and secret ARN 
to execute queries. No direct network connectivity to the database is required.

## When to activate

- CloudWatch alarms are firing on MotorOS services
- Telemetry pipeline is degraded or down
- OTA campaigns are stalled
- Any service in `motoros-prod` namespace is unhealthy
- BMS (Battery Management System) DTC codes are spiking
- ECU firmware rollbacks are detected

## Step 1: Identify affected services

Check which MotorOS services are degraded:
- Query EKS pods in `motoros-prod` namespace for CrashLoopBackOff, OOMKilled, or not Ready
- Check CloudWatch alarms with prefix `motoros3-` for ALARM state
- Note which service tier is affected: telemetry, OTA, fleet, dealer, or BMS

## Step 2: Quantify vehicle impact

Query the MotorOS Aurora database to determine impact:

### If telemetry pipeline is down:
```sql
-- Count vehicles that should be reporting but aren't
SELECT COUNT(*) as affected_vehicles 
FROM vehicles 
WHERE firmware_status != 'DECOMMISSIONED';

-- Break down by fleet
SELECT f.name as fleet_name, f.fleet_id, COUNT(v.id) as vehicle_count 
FROM vehicles v 
JOIN fleets f ON v.fleet_id = f.id 
GROUP BY f.name, f.fleet_id 
ORDER BY vehicle_count DESC;

-- Check last telemetry event per fleet (detect data gaps)
SELECT f.name as fleet_name, 
       MAX(te.event_time) as last_event,
       COUNT(DISTINCT te.vehicle_id) as reporting_vehicles
FROM telemetry_events te
JOIN vehicles v ON te.vehicle_id = v.id
JOIN fleets f ON v.fleet_id = f.id
WHERE te.event_time > NOW() - INTERVAL '1 hour'
GROUP BY f.name
ORDER BY last_event ASC;
```

### If OTA campaigns are stalled:
```sql
-- Count vehicles waiting for firmware (includes ECU-specific campaigns)
SELECT campaign_id, firmware_version, target_ecu, total_vehicles, 
       completed_vehicles, failed_vehicles,
       (total_vehicles - completed_vehicles - failed_vehicles) as vehicles_waiting
FROM ota_campaigns 
WHERE status = 'IN_PROGRESS';

-- Count vehicles in failed state
SELECT COUNT(*) as firmware_failures 
FROM vehicles 
WHERE firmware_status = 'FIRMWARE_UPDATE_FAILED';

-- Find vehicles in ROLLBACK status by ECU
SELECT ve.ecu_type, ve.firmware_version, COUNT(*) as rollback_count
FROM vehicle_ecus ve
WHERE ve.status = 'ROLLBACK'
GROUP BY ve.ecu_type, ve.firmware_version
ORDER BY rollback_count DESC;
```

### If dealer services are down:
```sql
-- Count pending orders affected
SELECT COUNT(*) as pending_orders, COUNT(DISTINCT dealer_code) as dealers_affected
FROM orders 
WHERE status = 'PENDING';
```

### Vehicles with ECU rollbacks (BMS cold-charging scenario):
```sql
-- Find all vehicles currently in ROLLBACK status
SELECT v.vin, ve.ecu_type, ve.firmware_version, ve.status, ve.updated_at
FROM vehicle_ecus ve
JOIN vehicles v ON ve.vehicle_id = v.id
WHERE ve.status = 'ROLLBACK'
ORDER BY ve.updated_at DESC;

-- Find the common firmware version across rolled-back ECUs
SELECT ve.ecu_type, ve.firmware_version, COUNT(*) as affected_count
FROM vehicle_ecus ve
WHERE ve.status = 'ROLLBACK'
  AND ve.ecu_type = 'BMS'
GROUP BY ve.ecu_type, ve.firmware_version
ORDER BY affected_count DESC
LIMIT 5;
```

## Step 2b: Investigate DTC anomalies

When DTC (Diagnostic Trouble Code) rates are spiking or a BMS cold-charging rollback 
is suspected, use these queries to correlate hardware faults with firmware and environment.

### Find recent DTCs grouped by code and severity:
```sql
SELECT dtc_code, severity, COUNT(*) as occurrence_count,
       COUNT(DISTINCT vehicle_id) as vehicles_affected,
       MIN(event_time) as first_seen,
       MAX(event_time) as last_seen
FROM dtc_events
WHERE event_time > NOW() - INTERVAL '24 hours'
GROUP BY dtc_code, severity
ORDER BY occurrence_count DESC
LIMIT 20;
```

### Correlate DTCs with ECU firmware versions:
```sql
SELECT de.dtc_code, de.severity, ve.ecu_type, ve.firmware_version,
       COUNT(*) as occurrences,
       COUNT(DISTINCT de.vehicle_id) as vehicles_affected
FROM dtc_events de
JOIN vehicle_ecus ve ON de.vehicle_id = ve.vehicle_id AND ve.ecu_type = 'BMS'
WHERE de.event_time > NOW() - INTERVAL '24 hours'
GROUP BY de.dtc_code, de.severity, ve.ecu_type, ve.firmware_version
ORDER BY occurrences DESC;
```

### Check if affected vehicles share a recent OTA campaign:
```sql
SELECT oc.campaign_id, oc.firmware_version, oc.target_ecu, oc.status,
       COUNT(DISTINCT de.vehicle_id) as dtc_vehicles_in_campaign
FROM dtc_events de
JOIN ota_campaigns oc ON oc.status IN ('IN_PROGRESS', 'COMPLETED')
  AND oc.target_ecu = 'BMS'
WHERE de.event_time > NOW() - INTERVAL '24 hours'
  AND de.vehicle_id IN (
    SELECT vehicle_id FROM vehicle_ecus 
    WHERE ecu_type = 'BMS' AND firmware_version = oc.firmware_version
  )
GROUP BY oc.campaign_id, oc.firmware_version, oc.target_ecu, oc.status
ORDER BY dtc_vehicles_in_campaign DESC;
```

### Look at telemetry conditions at time of DTC (ambient temp, cell voltages):
```sql
-- Check environmental conditions when DTCs fired (BMS cold-charging scenario)
SELECT de.dtc_code, de.vehicle_id, de.event_time,
       te.ambient_temp_c, te.soc_pct, 
       te.cell_voltage_min, te.cell_voltage_max,
       (te.cell_voltage_max - te.cell_voltage_min) as cell_voltage_delta
FROM dtc_events de
JOIN telemetry_events te ON de.vehicle_id = te.vehicle_id
  AND te.event_time BETWEEN de.event_time - INTERVAL '5 minutes' 
                         AND de.event_time + INTERVAL '5 minutes'
WHERE de.event_time > NOW() - INTERVAL '24 hours'
  AND de.dtc_code LIKE 'P0A%'  -- BMS-related DTCs
ORDER BY te.ambient_temp_c ASC
LIMIT 50;

-- Aggregate: what ambient temps are correlated with BMS DTCs?
SELECT 
  CASE 
    WHEN te.ambient_temp_c < -10 THEN 'extreme_cold (<-10C)'
    WHEN te.ambient_temp_c < 0 THEN 'cold (-10C to 0C)'
    WHEN te.ambient_temp_c < 10 THEN 'cool (0C to 10C)'
    ELSE 'normal (>10C)'
  END as temp_band,
  COUNT(*) as dtc_count,
  COUNT(DISTINCT de.vehicle_id) as vehicles_affected,
  AVG(te.soc_pct) as avg_soc,
  AVG(te.cell_voltage_min) as avg_cell_min_v,
  AVG(te.cell_voltage_max) as avg_cell_max_v
FROM dtc_events de
JOIN telemetry_events te ON de.vehicle_id = te.vehicle_id
  AND te.event_time BETWEEN de.event_time - INTERVAL '5 minutes' 
                         AND de.event_time + INTERVAL '5 minutes'
WHERE de.event_time > NOW() - INTERVAL '24 hours'
  AND de.dtc_code LIKE 'P0A%'
GROUP BY temp_band
ORDER BY dtc_count DESC;
```

### Trip context for affected vehicles:
```sql
-- Were vehicles on active trips when DTCs fired?
SELECT t.vehicle_id, t.trip_id, t.start_time, t.end_time, 
       t.distance_km, de.dtc_code, de.event_time
FROM trips t
JOIN dtc_events de ON t.vehicle_id = de.vehicle_id
  AND de.event_time BETWEEN t.start_time AND COALESCE(t.end_time, NOW())
WHERE de.event_time > NOW() - INTERVAL '24 hours'
ORDER BY de.event_time DESC
LIMIT 30;
```

## Step 3: Assess severity tier

Based on the numbers, classify the incident:

| Tier | Criteria | Escalation |
|------|----------|------------|
| SEV-1 Critical | >5000 vehicles offline OR safety-critical fleet affected OR OTA stalled >1hr OR BMS rollback affecting >500 vehicles | Page VP Engineering + Customer Success |
| SEV-2 High | 1000-5000 vehicles affected OR active OTA campaign stalled OR BMS DTC spike correlated with cold temps | Page on-call lead + notify fleet managers |
| SEV-3 Medium | <1000 vehicles, non-safety fleet, telemetry delay <15 min | Notify on-call, monitor |
| SEV-4 Low | Single fleet, <100 vehicles, no OTA impact | Log and monitor |

## Step 4: Generate impact statement

Produce a structured impact report:

```
INCIDENT IMPACT ASSESSMENT
═══════════════════════════════════════════════
Severity: [SEV-1/2/3/4]
Time of assessment: [UTC timestamp]

VEHICLE IMPACT:
  Total vehicles affected: [number]
  Fleets impacted: [list fleet names and counts]
  Safety-critical vehicles: [number, if any]
  Vehicles in ROLLBACK status: [number, by ECU type]

SERVICE IMPACT:
  Telemetry: [ONLINE / DEGRADED / OFFLINE] — last data [X] seconds ago
  OTA Delivery: [ACTIVE / STALLED / BLOCKED]
  Dealer Orders: [PROCESSING / DELAYED / BLOCKED]
  BMS Health: [NORMAL / DTC_SPIKE / ROLLBACK_ACTIVE]

CAMPAIGN IMPACT:
  Active campaigns stalled: [number]
  Vehicles waiting for firmware: [number]
  Vehicles in FIRMWARE_UPDATE_FAILED: [number]
  ECU rollbacks detected: [number, by ecu_type]

DTC ANALYSIS (if applicable):
  Top DTC code: [code] — [count] occurrences across [N] vehicles
  Correlated firmware: [version]
  Environmental factor: [e.g., ambient_temp_c < -10C in 80% of cases]

CUSTOMER COMMUNICATION:
  [One-line plain-English summary suitable for customer notification]

RECOMMENDED ACTIONS:
  1. [Primary action]
  2. [Secondary action]
  3. [Escalation if needed]
═══════════════════════════════════════════════
```

## Step 5: Recommend next steps

Based on severity:
- **SEV-1/2**: Recommend opening a formal investigation, suggest specific remediation
- **SEV-3/4**: Recommend monitoring with a follow-up check in 15 minutes

For **BMS cold-charging rollback** scenarios specifically:
1. Confirm the correlation between ambient temperature and DTC spike
2. Identify the firmware version that triggered rollbacks via `vehicle_ecus`
3. Check if a recent OTA campaign (by `target_ecu = 'BMS'`) introduced the regression
4. Recommend pausing the OTA campaign if rollbacks are still climbing
5. Quantify vehicles that successfully updated vs. rolled back to assess blast radius

Always note the **time sensitivity** — for OTA campaigns, every minute of delay means 
vehicles remain on vulnerable firmware. For telemetry, gaps in data mean fleet managers 
lose visibility into driver behavior and vehicle health. For BMS issues, vehicles in 
cold climates may be unable to charge safely until the firmware is corrected.
