---
name: offer-campaign-workflow
description: Design, build, review, or troubleshoot n8n workflows that turn customer segments into targeted offer campaigns. Use for campaign eligibility, offer assignment, previews, approval gates, delivery, and outcome logging. Keep historical or sample data in demo mode.
---

# Offer campaign workflow

Help create an n8n workflow for a targeted offer campaign, from customer input through delivery and logging. First establish whether the request is for a design, an editable workflow artifact, a workflow change, or a live campaign run. Treat preparing a campaign and sending messages as separate actions.

## Workflow design

1. Identify the source and shape of customer data, campaign objective, audience, offer options, delivery channel, and success measure. Reuse existing project schemas where available; do not assume a field exists because its name seems likely.
2. Build the workflow in clear stages:
   - Trigger or import the audience from an approved source.
   - Validate required fields, normalize identifiers and contact fields, and reject or quarantine malformed records.
   - Apply explicit eligibility rules and exclusions. Make the rules configurable and explain any defaults.
   - Enforce deduplication and contact frequency limits using a durable campaign or contact history where available.
   - Assign an offer and construct a message from reviewed templates. Keep personal data out of execution logs where possible.
   - Produce a preview with audience counts, segment and offer breakdowns, exclusions, and sample messages.
   - Add a human approval step before any live send. Approval should identify the campaign, audience, channel, message, and expected volume.
   - After approval, send in controlled batches with provider-appropriate rate limits and retry handling. Avoid retrying non-idempotent sends without checking delivery status.
   - Record campaign ID, customer key, assigned offer, approval, attempt status, provider result, and timestamps for audit and outcome analysis.
3. Use n8n nodes and connections that are available in the user's instance. Reference credentials by configured credential name; never request, expose, or embed secrets in workflow JSON or notes.
4. Include error branches for invalid input, missing credentials, provider failures, and partial sends. Make workflow runs resumable or safely repeatable where feasible.

## Safety and data handling

- Keep the workflow in preview or dry-run mode until the user explicitly asks to send a specific live campaign and its audience, message, channel, and volume are clear.
- Do not send messages merely because a workflow is being created, edited, imported, or tested. A preview or test send must use an explicitly designated test recipient or sandbox.
- Treat historical datasets such as Olist (2016–2018) as demonstration data. Do not use them to contact real people or present their old buying behavior as current.
- Minimize personal data in workflow nodes, exported artifacts, and logs. Do not add contact details to logs unless needed for delivery troubleshooting.
- Do not invent consent, legal basis, opt-out status, or business policy. Ask for the relevant field or rule when the workflow cannot safely determine eligibility.

## Deliverable

For a design request, provide a concise node-by-node plan with inputs, key mappings, branches, approval point, and outputs. For a workflow artifact, explain required credentials and configuration without including secrets. For a review, identify concrete node or connection issues and their effects. State assumptions and what could not be verified in the user's n8n instance.
