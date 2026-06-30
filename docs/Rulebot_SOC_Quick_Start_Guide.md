# SOC AI Rulebot — SOC Quick Start Guide

_Last updated: 2026-06-30_

## 1. Purpose

SOC AI Rulebot helps SOC analysts:

- look up QRadar rules
- understand QRadar rule logic and building block dependencies
- analyze QRadar offenses for possible false-positive tuning
- generate structured tuning recommendations
- reuse similar historical tuning cases
- create and track case records
- update case status after review or implementation

Rulebot is a **decision-support tool**. It does **not** automatically change QRadar rules.

---

## 2. Main Commands

### Rule lookup

Send a QRadar rule ID:

```text
124702
```

Rulebot returns:

- rule summary
- rule intent
- relevant logic/context
- tuning options
- sources used

---

### General QRadar question

Example:

```text
How do QRadar building blocks reduce false positives?
```

Rulebot returns a QRadar-focused answer using indexed documentation, rule knowledge, and internal context.

---

### New offense template

```text
new offense
```

Rulebot returns the offense-analysis template.

---

### Case lookup

```text
case CASE-20260624-XXXXXXX
```

---

### Case status update

```text
update case CASE-20260624-XXXXXXX implemented
```

Allowed case status values:

```text
proposed
under_review
implemented
rejected
```

---

## 3. PacketGenerator Workflow

Use the PacketGenerator script before submitting a real QRadar offense to Rulebot.

Current script location:

```text
tools/windows/Generate-QRadarPacket.ps1
```

### Analyst workflow

1. Open Windows PowerShell.
2. Navigate to the folder containing the script.
3. Run:

```powershell
.\Generate-QRadarPacket.ps1
```

4. Select the QRadar instance.
5. Enter the offense ID.
6. Enter QID if known.

QID is recommended because it narrows the Ariel search and improves the quality of the generated packet.

7. The script copies the generated offense template to the clipboard.
8. Paste the generated template into Rulebot.
9. Fill in the analyst fields:

```text
why_false_positive:
desired_outcome:
analyst_notes:
```

10. Send the completed packet to Rulebot.

---

## 4. PacketGenerator Setup Requirements

### QRadar address

Before first use, the QRadar IP or FQDN must be configured inside the script.

Example:

```powershell
BaseUrl = "https://<QRADAR-IP-OR-FQDN>"
```

For the Bahrain QRadar instance, this should point to the locally reachable QRadar address.

---

### QRadar API token

The QRadar SEC token must be available as a PowerShell environment variable.

For the current PowerShell session only:

```powershell
$env:QRADAR_BH_SEC_TOKEN = "<token>"
```

For persistent user-level storage:

```powershell
[Environment]::SetEnvironmentVariable(
  "QRADAR_BH_SEC_TOKEN",
  "<token>",
  "User"
)
```

Restart PowerShell after setting the persistent variable.

Verify that the variable exists:

```powershell
$env:QRADAR_BH_SEC_TOKEN.Length
```

If a number is returned, the variable is set.

Do **not** paste API tokens into:

- Teams
- Rulebot prompts
- documentation
- Git
- screenshots
- shared chat messages

---

## 5. Offense Analysis Template

The canonical offense-analysis template is:

```text
offense_id:
client_id:
rule_id:
event_name:
event_description:
source_ip:
source_port:
destination_ip:
destination_port:
username:
log_source:
qid:
category:
magnitude:
start_time:
event_count:
payload_summary:
why_false_positive:
desired_outcome:
analyst_notes:
```

Minimum required fields:

```text
rule_id
why_false_positive
desired_outcome
```

The PacketGenerator fills many fields automatically from QRadar offense and Ariel event data.

Analysts should manually complete:

```text
why_false_positive:
desired_outcome:
analyst_notes:
```

---

## 6. Example Completed Analyst Fields

Example:

```text
why_false_positive: Legitimate administrative activity
desired_outcome: Only alert when there are 10 failed API requests within 15 minutes
analyst_notes: Activity relates to approved integration testing
```

Good analyst input should clearly explain:

- why the offense is believed to be benign
- what the analyst wants the rule to do instead
- any business or operational context that matters

---

## 7. How to Interpret an Offense Analysis Response

Rulebot offense analysis usually includes:

- classification
- confidence
- case ID
- assessment
- similar historical cases, if any
- false-positive rationale
- desired outcome
- analyst notes
- recommended tuning options
- suggested validation steps
- sources used

---

## 8. Recommended Tuning Options

Good Rulebot tuning recommendations should be concrete and actionable.

Examples of useful recommendation types:

- change event condition from success to failure
- add threshold logic
- increase or decrease threshold values
- scope to a specific log source
- exclude approved shared/service accounts
- refine a building block
- reuse an existing building block
- adjust grouping fields
- narrow by QID, category, source, destination, or username

If a recommendation seems too generic, analysts should flag it during pilot feedback.

---

## 9. Case Memory

Every offense analysis can create a case ID.

Example:

```text
CASE-20260624-9D6B718A
```

Use the case ID to retrieve or update the case.

### Retrieve a case

```text
case CASE-20260624-9D6B718A
```

### Update case status

```text
update case CASE-20260624-9D6B718A under_review
```

Allowed status values:

```text
proposed
under_review
implemented
rejected
```

A case should be treated as a historical snapshot of:

- offense context
- rule context
- analyst rationale
- Rulebot recommendation
- sources used at the time

Normally, only the **case status** should be updated after creation.

---

## 10. Similar Historical Cases

Rulebot may show similar historical cases.

Important interpretation:

- same-client cases are usually more relevant
- cross-client cases are supporting reference only
- analysts should not blindly apply tuning from another client
- different clients may have different business workflows, approved behavior, maintenance windows, and compliance requirements

Similar cases are intended to help analysts reason faster, not to replace review.

---

## 11. How to Judge a Rulebot Answer

During pilot use, analysts should evaluate:

1. Did Rulebot understand the offense correctly?
2. Were the recommendations specific and actionable?
3. Did the recommendation preserve detection coverage?
4. Did the recommendation match actual QRadar tuning practice?
5. Were similar historical cases relevant?
6. Were the sources used appropriate?
7. Was any important packet field missing?
8. Was the response clear enough for SOC workflow?

---

## 12. PacketGenerator Timing Caveat

The PacketGenerator uses bounded Ariel searches to avoid expensive unbounded queries.

Current behavior:

- frequency/count query uses a recent fixed time window
- sample event query uses a broader recent time window
- QID is strongly recommended to narrow the Ariel search

If the offense is old or the QID is not provided, some sample fields may be less reliable or may remain blank.

Future improvement under consideration:

```text
Use an offense-time-centered search window around the offense start time.
```

SOC feedback should indicate whether the current search windows are sufficient.

---

## 13. What Rulebot Is Not

Rulebot is not:

- an automatic QRadar rule changer
- a final approval authority
- a replacement for analyst judgement
- a substitute for change control
- a guarantee that a rule change is safe

Analysts remain responsible for validating recommendations before implementation.

---

## 14. Recommended Pilot Feedback

Please report:

- incorrect recommendations
- recommendations that are too generic
- missing PacketGenerator fields
- confusing response formatting
- irrelevant similar cases
- cases where rule or building block context was missing
- cases where the recommendation was useful and should become a repeatable pattern
- any offense type where Rulebot performs especially well or poorly

---

## 15. Quick Reference

### Start offense workflow

```text
new offense
```

### Run PacketGenerator

```powershell
.\Generate-QRadarPacket.ps1
```

### Lookup rule

```text
124702
```

### Retrieve case

```text
case CASE-20260624-XXXXXXX
```

### Update case

```text
update case CASE-20260624-XXXXXXX implemented
```

### Allowed case statuses

```text
proposed
under_review
implemented
rejected
```

---

## 16. Recommended Mindset

Use Rulebot as:

- a decision accelerator
- a QRadar rule tuning assistant
- a knowledge reuse tool
- a case-memory system

Do not use Rulebot as:

- an autonomous rule modifier
- a replacement for SOC judgement
- an approval mechanism

Final tuning decisions should always remain under SOC review and normal change-control processes.