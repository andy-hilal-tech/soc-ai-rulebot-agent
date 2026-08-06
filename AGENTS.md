# Rulebot Agent Instructions

This repository is the SOC Rulebot project.

Rulebot helps analysts review QRadar rules, understand rule noise, and generate safe rule tuning recommendations.

## Core Purpose

Rulebot should help analysts answer:

- What does this QRadar rule do?
- Why is this rule noisy?
- What evidence suggests the rule should be tuned?
- What safe tuning options exist?
- How should an approved analyst implement the tuning change in QRadar?
- How should the change be validated and rolled back?

## Non-Negotiable Constraints

- Do not modify QRadar rules directly.
- Do not generate instructions that imply the bot can deploy QRadar rule changes automatically.
- Do not invent QRadar field names, test names, reference sets, building blocks, or rule logic that are not present in the evidence.
- If exact QRadar implementation details are missing, clearly state what must be confirmed by a senior analyst.
- Always separate:
  - Observed evidence
  - Interpretation
  - Recommendation
  - Implementation guidance
  - Risks
  - Validation
  - Rollback
- Prefer safe, senior-analyst-reviewable recommendations.
- Do not recommend suppressing alerts without explaining the risk.
- Do not recommend excluding users, hosts, IPs, services, or events unless the evidence supports it.
- Do not remove or weaken security logic without documenting expected impact and rollback.
- Do not hardcode secrets, tokens, QRadar URLs, API keys, or credentials.
- Do not use `DATABASE_URL` unless the existing project already uses it.
- Do not introduce new dependencies unless explicitly requested.

## Required Rulebot Output Direction

Rulebot must evolve from generic tuning advice to actionable implementation guidance.

Every rule tuning output should eventually include:

1. Rule Summary
2. Current Noise / False Positive Drivers
3. Recommended Tuning Change
4. QRadar Rule Tuning Implementation Guide
5. Validation Plan
6. Rollback Plan
7. Risk / Analyst Approval Notes

## QRadar Rule Tuning Implementation Guide

When enough information is available, this section should include:

- Exact QRadar UI navigation path
- Rule name
- Rule test group or condition area to review
- Suggested condition/test to add or modify
- Exact values to add, exclude, or tune
- Whether to use a reference set, building block, event property, rule test, or manual condition
- Expected impact
- Risk of false negatives
- Validation period
- Rollback steps

If exact QRadar field names, reference sets, building blocks, or test names are not available, Rulebot must say so clearly.

Example wording:

"Exact QRadar property name must be confirmed by a senior analyst before implementation."

## Implementation Guidance Style

The implementation guidance should be written so that a less experienced analyst can follow it after a senior analyst approves the recommendation.

Preferred style:

1. Open QRadar Console.
2. Navigate to the relevant rule or rule group.
3. Locate the relevant test or condition.
4. Add or modify the specified condition.
5. Save.
6. Deploy changes.
7. Monitor results.
8. Roll back if needed.

## Safety Requirements for Tuning

Every tuning recommendation must include:

- Why the change is recommended
- What evidence supports the change
- What could be missed if the change is wrong
- How to validate after deployment
- How to roll back

## Current Known SOC Need

The SOC team needs detailed QRadar tuning implementation guidance.

Generic advice like:

"Add a condition to match the Message field"

is not enough.

Rulebot should aim to produce operational SOP-style guidance such as:

- where to click
- what rule condition to add
- what values to insert
- what to validate
- what to monitor
- how to roll back

## Agent Behavior

- Make small, reviewable changes.
- Inspect relevant files before editing.
- Do not refactor unrelated code.
- Run only relevant tests.
- Summarize changed files and test results.
- Ask for clarification if the repository structure is ambiguous.