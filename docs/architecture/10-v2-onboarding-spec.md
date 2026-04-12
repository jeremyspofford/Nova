# 10 – v2 Features: Onboarding & Deployment Assistant

This document captures the v2 onboarding and deployment assistant concept discussed during architecture planning.

## Purpose

The onboarding assistant will:
- survey the user’s available hardware and deployment preferences
- recommend an optimal Nova deployment topology
- generate deployment scripts and IaC tailored to that topology

This makes Nova accessible to users with different setups without requiring deep systems knowledge.

## User interaction flow

1. **Hardware survey**
   - "What devices do you have? (Pi 4/5, mini PC, GPU tower, cloud credits, etc.)"
   - "What’s your priority? (privacy/local-only, ease of use, maximum capability)"
   - "Do you have Home Assistant already? VPN? DNS sinkhole?"

2. **Recommendation**
   - Suggest component placement:
     - Pi 4 → HA + lightweight state sync
     - Mini PC → Nova API/Board/state/workflow
     - GPU tower → local LLM + Nova-lite
     - Cloud → optional n8n/Windmill/observability
   - Show security posture (VPN recommended, DNS sinkhole recommended)

3. **IaC generation**
   - Generate Docker Compose or Terraform based on choices
   - Include VPN/DNS setup if missing
   - Pre-fill with recommended configs (tool mappings, LLM providers)

4. **Review and apply**
   - Show generated files
   - Offer one-click apply (with confirmation)
   - Post-deployment validation

## Implementation notes

- Lives as a future subsystem behind Nova API
- Uses LLM provider for natural-language hardware parsing and recommendation
- Outputs to files or clipboard for review
- Never auto-applies without explicit confirmation

## Integration with existing architecture

- Uses deployment modes from 03-deployment-modes.md
- Generates configs for tools, LLM providers, state sync from survey answers
- Extends the deployment diagram to include hardware-specific placement

This feature is explicitly v2 to keep MVP focused, but designing for it now ensures future compatibility.
