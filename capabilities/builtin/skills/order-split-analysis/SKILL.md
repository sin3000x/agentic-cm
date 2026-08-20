---
name: order-split-analysis
description: Analyze partial and staged delivery options for an approved OrderSplit Path. Use after Manifest approval to produce a reviewable split-delivery proposal without changing an order or committing a customer date.
---

# Analyze order split

1. Read the frozen Case snapshot, HumanProposal, compiled Policy, and current available-quantity evidence.
2. Build shipment batches only from supported quantities and dates.
3. Separate the immediately deliverable quantity, remaining quantity, proposed batches, customer acceptance, and remaining commitment.
4. Mark unsupported quantities, dates, or customer assumptions as awaiting confirmation from the responsible role.
5. Return `OrderSplitSolutionRevision/v1` with `available_quantity`, `shipment_batches`, `customer_acceptance`, `remaining_commitment`, and `overall_recommendation` sections.

Do not represent planning, logistics, sales, the customer, or the Case Owner. Do not modify ERP, inventory, order, logistics, CRM, or customer systems.
