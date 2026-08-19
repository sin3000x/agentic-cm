---
name: material-substitution-analysis
description: Analyze approved material-substitution candidates for a supply-chain Case and produce a structured, reviewable proposal. Use when an approved MaterialSubstitution Path needs supply, technical, customer, and overall recommendation sections without making business commitments or changing operational systems.
---

# Analyze material substitution

1. Read the frozen Case snapshot, HumanProposal, compiled Policy, and referenced Knowledge.
2. Analyze only the candidate set approved in the Manifest. Do not introduce a new candidate without requesting a Path revision.
3. Separate supply feasibility, technical feasibility, customer acceptance, and the overall recommendation.
4. Mark every conclusion without current evidence as awaiting confirmation from the responsible role.
5. Treat historical Knowledge as advisory context, never as a current Case fact.
6. Return `MaterialSubstitutionSolutionRevision/v1` with the required `supply`, `technical`, `customer`, and `overall_recommendation` sections.

Do not represent the supply planner, engineering, frontline manager, or Case Owner. Do not remove compiled Policy requirements. Do not connect to or modify ERP, inventory, order, CRM, or customer systems.
