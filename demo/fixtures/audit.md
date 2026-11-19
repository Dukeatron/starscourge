# Compliance Audit Log
**Report ID:** AUD-20261119T085700Z  
**Generated (UTC):** 2026-11-19T08:57:00Z  
**Detected by:** AI Compliance Engine (model: qwen2.5-coder:14b)

## 1. Executive Summary
This audit identified 9 compliance anomalies. There are 1 high-severity finding, 7 medium-severity findings, and no low-severity findings. The most serious risk is related to the NTP source not being traceable to NIC or NPL, which could impact the accuracy and reliability of time synchronization across the company's systems. The overall compliance posture is moderately compromised, requiring immediate attention to the high-severity issue and planned actions for the medium-severity issues.

## 2. Findings Summary

| ID       | Title                                      | Severity | Gap Type       | Status |
|----------|--------------------------------------------|----------|----------------|--------|
| ANOM-001 | NTP Source Not Traceable to NPL or NIC    | high     | non_compliant  | Open   |
| ANOM-002 | Cyber Incident Reporting SLA Exceeds Requirement | medium | non_compliant  | Open   |
| ANOM-003 | Point of Contact Details Not Submitted     | medium | non_compliant  | Open   |
| ANOM-004 | Insufficient Logging for Network Firewalls | medium | non_compliant  | Open   |
| ANOM-005 | Insufficient Logging for VPN Concentrator  | medium | non_compliant  | Open   |
| ANOM-006 | Insufficient Logging for Corporate Laptops | medium | non_compliant  | Open   |
| ANOM-007 | Log Retention Period Shorter than Required | medium | non_compliant  | Open   |
| ANOM-008 | Logs Not Stored in Indian Jurisdiction    | medium | non_compliant  | Open   |
| ANOM-009 | Insufficient Information on NTP Drift Monitoring | medium | insufficient_information | Open   |

## 3. Detailed Findings

### ANOM-001 — NTP Source Not Traceable to NPL or NIC
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** high  
- **Category:** security
- **Regulation requirement:** Connect to NTP Server of NIC or NPL or traceable NTP servers.
- **Regulation excerpt:** "shall connect to the Network Time Protocol (NTP) Server of National Informatics Centre (NIC) or National Physical Laboratory (NPL) or with NTP servers traceable to these NTP servers"
- **Current state:** ntp_source_corporate_endpoints = time.windows.com, ntp_source_production = Amazon Time Sync Service (169.254.169.123)
- **Gap:** The company's NTP sources are not traceable to NIC or NPL.
- **Proposed remediation plan:**
  1. Switch to NTP servers traceable to NIC or NPL.
  2. Ensure all endpoints are configured to use the new NTP servers.
  3. Verify the configuration and connectivity to the new NTP servers.
- **Status:** Open

### ANOM-002 — Cyber Incident Reporting SLA Exceeds Requirement
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** medium  
- **Category:** reporting
- **Regulation requirement:** Report cyber incidents within 6 hours.
- **Regulation excerpt:** "shall mandatorily report cyber incidents as mentioned in Annexure I to CERT-In within 6 hours of noticing such incidents"
- **Current state:** cert_in_reporting_sla_hours = 24, cert_in_reporting_trigger = after SEV1/SEV2 triage is complete
- **Gap:** The company's reporting SLA is 24 hours, exceeding the required 6 hours.
- **Proposed remediation plan:**
  1. Reduce the reporting SLA to 6 hours.
  2. Ensure immediate reporting upon incident detection.
  3. Update the incident response plan to reflect the new SLA.
- **Status:** Open

### ANOM-003 — Point of Contact Details Not Submitted
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** medium  
- **Category:** governance
- **Regulation requirement:** Submit Point of Contact details to CERT-In.
- **Regulation excerpt:** "The Information relating to a Point of Contact shall be sent to CERT-In in the format specified at Annexure II"
- **Current state:** cert_in_poc_details_submitted = false, cert_in_poc_last_updated = null
- **Gap:** The company has not submitted Point of Contact details to CERT-In.
- **Proposed remediation plan:**
  1. Submit the Point of Contact details to CERT-In as per the specified format.
  2. Verify the submission and receipt confirmation.
- **Status:** Open

### ANOM-004 — Insufficient Logging for Network Firewalls
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** medium  
- **Category:** security
- **Regulation requirement:** Enable logs for all ICT systems.
- **Regulation excerpt:** "All service providers, intermediaries, data centres, body corporate and Government organisations shall mandatorily enable logs of all their ICT systems"
- **Current state:** ict_logging_not_enabled_for = ["network firewalls"]
- **Gap:** Network firewalls are not included in the logging.
- **Proposed remediation plan:**
  1. Enable logging for network firewalls.
  2. Ensure they are included in the rolling retention period.
  3. Verify the logging configuration and data collection.
- **Status:** Open

### ANOM-005 — Insufficient Logging for VPN Concentrator
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** medium  
- **Category:** security
- **Regulation requirement:** Enable logs for all ICT systems.
- **Regulation excerpt:** "All service providers, intermediaries, data centres, body corporate and Government organisations shall mandatorily enable logs of all their ICT systems"
- **Current state:** ict_logging_not_enabled_for = ["VPN concentrator"]
- **Gap:** VPN concentrator is not included in the logging.
- **Proposed remediation plan:**
  1. Enable logging for VPN concentrator.
  2. Ensure it is included in the rolling retention period.
  3. Verify the logging configuration and data collection.
- **Status:** Open

### ANOM-006 — Insufficient Logging for Corporate Laptops
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** medium  
- **Category:** security
- **Regulation requirement:** Enable logs for all ICT systems.
- **Regulation excerpt:** "All service providers, intermediaries, data centres, body corporate and Government organisations shall mandatorily enable logs of all their ICT systems"
- **Current state:** ict_logging_not_enabled_for = ["corporate laptops"]
- **Gap:** Corporate laptops are not included in the logging.
- **Proposed remediation plan:**
  1. Enable logging for corporate laptops.
  2. Ensure they are included in the rolling retention period.
  3. Verify the logging configuration and data collection.
- **Status:** Open

### ANOM-007 — Log Retention Period Shorter than Required
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** medium  
- **Category:** data_retention
- **Regulation requirement:** Maintain logs for 180 days.
- **Regulation excerpt:** "(iv) All service providers, intermediaries, data centres, body corporate and Government organisations shall mandatorily enable logs of all their ICT systems and maintain them securely for a rolling"
- **Current state:** ict_log_retention_days = 90
- **Gap:** The log retention period is 90 days, shorter than the required 180 days.
- **Proposed remediation plan:**
  1. Increase the log retention period to 180 days.
  2. Update the log management policy and procedures.
  3. Verify the retention settings across all systems.
- **Status:** Open

### ANOM-008 — Logs Not Stored in Indian Jurisdiction
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** medium  
- **Category:** data_retention
- **Regulation requirement:** Store logs within Indian jurisdiction.
- **Regulation excerpt:** "the same shall be maintained within the Indian jurisdiction"
- **Current state:** ict_log_storage = Splunk Cloud, us-east-1 (N. Virginia)
- **Gap:** Logs are stored in the US, not within the Indian jurisdiction.
- **Proposed remediation plan:**
  1. Move log storage to an Indian jurisdiction, such as AWS regions in India.
  2. Update the log management infrastructure to comply with the new storage location.
  3. Verify the data storage compliance and security.
- **Status:** Open

### ANOM-009 — Insufficient Information on NTP Drift Monitoring
- **Detected at (UTC):** 2026-11-19T08:57:00Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** medium  
- **Category:** security
- **Regulation requirement:** Monitor NTP drift against NPL or NIC.
- **Regulation excerpt:** "shall connect to the Network Time Protocol (NTP) Server of National Informatics Centre (NIC) or National Physical Laboratory (NPL) or with NTP servers traceable to these NTP servers"
- **Current state:** Not specified in company state
- **Gap:** There is no information on NTP drift monitoring against NPL or NIC.
- **Proposed remediation plan:**
  1. Implement NTP drift monitoring against NPL or NIC.
  2. Document the process and procedures for NTP drift monitoring.
  3. Verify the implementation and effectiveness of the monitoring.
- **Status:** Open

## 4. Audit Trail

| Timestamp (UTC)          | Event                                      | Actor                |
|--------------------------|--------------------------------------------|----------------------|
| 2026-11-19T08:57:00Z     | Gap analysis run                           | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-001 logged (high)                      | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-002 logged (medium)                    | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-003 logged (medium)                    | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-004 logged (medium)                    | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-005 logged (medium)                    | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-006 logged (medium)                    | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-007 logged (medium)                    | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-008 logged (medium)                    | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | ANOM-009 logged (medium)                    | AI Compliance Engine |
| 2026-11-19T08:57:00Z     | Report generated                           | AI Compliance Engine |
