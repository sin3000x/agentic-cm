from .capabilities import CapabilityRegistry
from .domain import Case, CaseStatus, Manifest, ManifestPath, OrchestrationPhase


def demo_cases(capabilities: CapabilityRegistry) -> list[Case]:
    classification = {
        "organization": "demo-supply-chain",
        "case_type": "ORDER_DELIVERY_RISK",
    }
    path_definition = "MaterialSubstitution"
    resolution = capabilities.resolve(classification | {"path_definition": path_definition})
    snapshot = resolution.to_snapshot()
    policy_refs = tuple(f"{item.id}@{item.version}" for item in resolution.policies)
    skill_refs = tuple(f"{item.id}@{item.version}" for item in resolution.skills)
    knowledge_refs = tuple(f"{item.id}@{item.version}" for item in resolution.knowledge)
    primary = Case(
        id="CM-2026-014", title="订单预计延期",
        description="订单 SO-48392 的关键物料预计晚于承诺日期 12 天，可能影响客户交付。",
        status=CaseStatus.OPEN, phase=OrchestrationPhase.MANIFEST_REVIEW,
        owner="陈澄", owner_role="订单履行经理",
        business_payload={"order_id": "SO-48392", "customer": "Northstar Mobility", "material": "MCU-X7", "gap_quantity": 18400, "target_date": "2026-08-24"},
        human_proposal={"revision": 1, "author": "陈澄", "role": "订单履行经理", "content": "建议优先评估现有认证范围内的替代物料，避免直接承诺未经客户确认的新方案。"},
        classification=classification,
        manifest=Manifest(
            id="MAN-CM-2026-014-1", revision=1, status="DRAFT",
            paths=(ManifestPath(id="PATH-01", definition=path_definition, title="物料替代", rationale="并行确认 A/B 的供应、技术与客户接受度。"),),
            policy_refs=policy_refs,
            skill_refs=skill_refs,
            knowledge_refs=knowledge_refs,
            experience_refs=knowledge_refs,
            capability_snapshot=snapshot,
        ),
    )
    related = [
        ("CM-2026-012", "供应商交付异常", "OPEN"),
        ("CM-2026-015", "替代料认证缺口", "OPEN"),
        ("CM-2026-009", "备件需求激增", "OPEN"),
        ("CM-2026-006", "华南仓到货差异", "CLOSED"),
    ]
    return [primary] + [
        Case(id=case_id, title=title, description="固定演示 Case", status=CaseStatus(status), phase=OrchestrationPhase.INTAKE, owner="陈澄", owner_role="订单履行经理", business_payload={}, human_proposal=None)
        for case_id, title, status in related
    ]
