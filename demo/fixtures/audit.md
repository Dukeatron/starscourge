# Compliance Audit Log
**Report ID:** AUD-20261119T083932Z
**Generated (UTC):** 2026-11-19T08:39:32Z
**Detected by:** AI Compliance Engine (model: qwen2.5-coder:14b)

## 1. Executive Summary

The automated compliance gap analysis detected 9 anomalies (3 high, 6 medium). Priority attention is required for 3 critical or high severity finding(s), led by ANOM-001 (NTP Source Not Traceable to NPL or NIC). All findings are open and each has a proposed remediation plan below.

## 2. Findings Summary

| ID | Title | Severity | Gap Type | Status |
| --- | --- | --- | --- | --- |
| ANOM-001 | NTP Source Not Traceable to NPL or NIC | High | Non-compliant | Open |
| ANOM-002 | Log Retention Period Too Short | High | Non-compliant | Open |
| ANOM-003 | Log Storage Outside Indian Jurisdiction | High | Non-compliant | Open |
| ANOM-004 | Cyber Incident Reporting SLA Exceeds Requirement | Medium | Non-compliant | Open |
| ANOM-005 | Insufficient Information on POC Details Submission | Medium | Insufficient information | Open |
| ANOM-006 | Insufficient Logging for Network Firewalls | Medium | Non-compliant | Open |
| ANOM-007 | Insufficient Logging for VPN Concentrator | Medium | Non-compliant | Open |
| ANOM-008 | Insufficient Logging for Corporate Laptops | Medium | Non-compliant | Open |
| ANOM-009 | Insufficient Information on NTP Drift Monitoring | Medium | Insufficient information | Open |

## 3. Detailed Findings

### ANOM-001 — NTP Source Not Traceable to NPL or NIC

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** High | **Category:** security
- **Regulation requirement:** Connect to NTP Server of NIC or NPL or traceable NTP servers.
- **Regulation excerpt:** "shall connect to the Network Time Protocol (NTP) Server of National Informatics Centre (NIC) or National Physical Laboratory (NPL) or with NTP servers traceable to these NTP servers"
- **Current state:** ntp_source_corporate_endpoints = time.windows.com, ntp_source_production = Amazon Time Sync Service (169.254.169.123)
- **Gap:** The company's NTP sources are not traceable to NIC or NPL.
- **Proposed remediation plan:**
  1. Switch to NTP servers traceable to NIC or NPL and update the configuration.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Chief Information Security Officer
  - **Target timeframe:** within 14 days of the report date
- **Status:** Open

### ANOM-002 — Log Retention Period Too Short

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** High | **Category:** data_retention
- **Regulation requirement:** Maintain logs for 180 days.
- **Regulation excerpt:** "(iv) All service providers, intermediaries, data centres, body corporate and Government organisations shall mandatorily enable logs of all their ICT systems and maintain them securely for a rolling"
- **Current state:** ict_log_retention_days = 90
- **Gap:** The log retention period is 90 days, which is less than the required 180 days.
- **Proposed remediation plan:**
  1. Increase the log retention period to 180 days and ensure compliance.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Data Protection Officer
  - **Target timeframe:** within 14 days of the report date
- **Status:** Open

### ANOM-003 — Log Storage Outside Indian Jurisdiction

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** High | **Category:** data_retention
- **Regulation requirement:** Maintain logs within Indian jurisdiction.
- **Regulation excerpt:** "the same shall be maintained within the Indian jurisdiction"
- **Current state:** ict_log_storage = Splunk Cloud, us-east-1 (N. Virginia)
- **Gap:** Logs are stored in the US, outside the Indian jurisdiction.
- **Proposed remediation plan:**
  1. Move log storage to an Indian jurisdiction and ensure compliance.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Data Protection Officer
  - **Target timeframe:** within 14 days of the report date
- **Status:** Open

### ANOM-004 — Cyber Incident Reporting SLA Exceeds Requirement

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** Medium | **Category:** reporting
- **Regulation requirement:** Report cyber incidents within 6 hours.
- **Regulation excerpt:** "shall mandatorily report cyber incidents as mentioned in Annexure I to CERT-In within 6 hours of noticing such incidents"
- **Current state:** cert_in_reporting_sla_hours = 24, cert_in_reporting_trigger = after SEV1/SEV2 triage is complete
- **Gap:** The company's reporting SLA is 24 hours, exceeding the required 6 hours.
- **Proposed remediation plan:**
  1. Reduce the reporting SLA to 6 hours and ensure compliance with the trigger condition.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Head of Compliance
  - **Target timeframe:** within 30 days of the report date
- **Status:** Open

### ANOM-005 — Insufficient Information on POC Details Submission

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** Medium | **Category:** governance
- **Regulation requirement:** Submit Point of Contact details to CERT-In.
- **Regulation excerpt:** "The Information relating to a Point of Contact shall be sent to CERT-In in the format specified at Annexure II"
- **Current state:** Not specified in company state
- **Gap:** The company has not submitted Point of Contact details to CERT-In.
- **Proposed remediation plan:**
  1. Submit the Point of Contact details to CERT-In as per the specified format.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Chief Compliance Officer
  - **Target timeframe:** within 30 days of the report date
- **Status:** Open

### ANOM-006 — Insufficient Logging for Network Firewalls

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** Medium | **Category:** security
- **Regulation requirement:** Enable logs for all ICT systems.
- **Regulation excerpt:** "All service providers, intermediaries, data centres, body corporate and Government organisations shall mandatorily enable logs of all their ICT systems"
- **Current state:** ict_logging_not_enabled_for = ["network firewalls"]
- **Gap:** Network firewalls are not logged.
- **Proposed remediation plan:**
  1. Enable logging for network firewalls and ensure they are included in the log retention policy.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Chief Information Security Officer
  - **Target timeframe:** within 30 days of the report date
- **Status:** Open

### ANOM-007 — Insufficient Logging for VPN Concentrator

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** Medium | **Category:** security
- **Regulation requirement:** Enable logs for all ICT systems.
- **Regulation excerpt:** "All service providers, intermediaries, data centres, body corporate and Government organisations shall mandatorily enable logs of all their ICT systems"
- **Current state:** ict_logging_not_enabled_for = ["VPN concentrator"]
- **Gap:** VPN concentrator is not logged.
- **Proposed remediation plan:**
  1. Enable logging for VPN concentrator and ensure it is included in the log retention policy.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Chief Information Security Officer
  - **Target timeframe:** within 30 days of the report date
- **Status:** Open

### ANOM-008 — Insufficient Logging for Corporate Laptops

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** Medium | **Category:** security
- **Regulation requirement:** Enable logs for all ICT systems.
- **Regulation excerpt:** "All service providers, intermediaries, data centres, body corporate and Government organisations shall mandatorily enable logs of all their ICT systems"
- **Current state:** ict_logging_not_enabled_for = ["corporate laptops"]
- **Gap:** Corporate laptops are not logged.
- **Proposed remediation plan:**
  1. Enable logging for corporate laptops and ensure they are included in the log retention policy.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Chief Information Security Officer
  - **Target timeframe:** within 30 days of the report date
- **Status:** Open

### ANOM-009 — Insufficient Information on NTP Drift Monitoring

- **Detected at (UTC):** 2026-11-19T08:39:32Z
- **Detection method:** Automated AI gap analysis of the company state against the supplied regulation text
- **Severity:** Medium | **Category:** security
- **Regulation requirement:** Monitor NTP drift against NPL or NIC.
- **Regulation excerpt:** "shall connect to the Network Time Protocol (NTP) Server of National Informatics Centre (NIC) or National Physical Laboratory (NPL) or with NTP servers traceable to these NTP servers"
- **Current state:** Not specified in company state
- **Gap:** There is no information on NTP drift monitoring against NPL or NIC.
- **Proposed remediation plan:**
  1. Implement NTP drift monitoring against NPL or NIC and document the process.
  2. Verify the fix with evidence and close the finding in the compliance register.
  - **Suggested owner:** Chief Information Security Officer
  - **Target timeframe:** within 30 days of the report date
- **Status:** Open

## 4. Audit Trail

| Timestamp (UTC) | Event | Actor |
| --- | --- | --- |
| 2026-11-19T08:39:32Z | Compliance gap analysis completed: 9 anomalies detected | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-001 logged (high) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-002 logged (high) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-003 logged (high) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-004 logged (medium) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-005 logged (medium) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-006 logged (medium) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-007 logged (medium) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-008 logged (medium) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | ANOM-009 logged (medium) | AI Compliance Engine |
| 2026-11-19T08:39:32Z | Audit log AUD-20261119T083932Z generated | AI Compliance Engine |
