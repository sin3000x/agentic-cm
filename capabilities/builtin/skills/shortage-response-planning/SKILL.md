---
name: shortage-response-planning
description: Evaluate every declared response path for a material-shortage or order-delivery-risk Case without making operational commitments. Use during orchestration before a Manifest is approved.
---

# Plan shortage response paths

Evaluate the current Case facts and HumanProposal against every Path supplied from this Skill package's `paths.json`. Return every supplied Path exactly once; rank and explain them, but do not omit a Path or invent another one. The Owner chooses which Paths proceed during Manifest Review.

For each Path, explain which current Case facts make it relevant. Do not treat historical Knowledge as current evidence. Do not approve a Path, make a business commitment, or modify ERP, inventory, order, supplier, logistics, CRM, or customer systems.
