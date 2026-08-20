---
name: supply-expediting-analysis
description: Analyze supplier, production, and logistics acceleration options for an approved SupplyExpediting Path. Use after Manifest approval to produce a reviewable proposal without making supplier or delivery commitments.
---

# Analyze supply expediting

1. Read the frozen Case snapshot, HumanProposal, compiled Policy, and current supplier and logistics evidence.
2. Separate supplier capacity, earliest feasible supply date, production priority, transport option, and expected arrival date.
3. Mark unsupported dates or quantities as awaiting confirmation from the responsible role.
4. Return `SupplyExpeditingSolutionRevision/v1` with `supplier_capacity`, `expedite_date`, `transport_option`, `arrival_date`, and `overall_recommendation` sections.

Do not represent procurement, the supplier, logistics, or the Case Owner. Do not make commitments or modify supplier, production, logistics, ERP, inventory, or order systems.
