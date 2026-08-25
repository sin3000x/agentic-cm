from .domain import Case, CaseStatus, OrchestrationPhase


DEMO_DATASET_ID = "supply-chain-golden-path-v1"
LEGACY_DEMO_TITLES = {
    "CM-2026-014": "订单预计延期",
    "CM-2026-012": "供应商交付异常",
    "CM-2026-015": "替代料认证缺口",
    "CM-2026-009": "备件需求激增",
    "CM-2026-006": "华南仓到货差异",
}


def demo_cases() -> list[Case]:
    common = {
        "owner": "陈澄",
        "owner_role": "订单统筹经理",
        "phase": OrchestrationPhase.INTAKE,
    }
    return [
        Case(
            id="CM-2026-014",
            title="Northstar Mobility MCU-X7 订单预计延期 12 天",
            description="订单 SO-48392 的关键物料预计晚于承诺日期 12 天，可能影响客户交付。",
            status=CaseStatus.OPEN,
            business_payload={
                "order_id": "SO-48392",
                "customer": "Northstar Mobility",
                "material": "MCU-X7",
                "gap_quantity": 18400,
                "target_date": "2026-08-24",
                "commitment_due_date": "2026-08-28",
                "risk_level": "HIGH",
            },
            human_proposal={
                "revision": 1,
                "author": "陈澄",
                "role": "订单统筹经理",
                "content": "建议优先评估现有认证范围内的替代物料，避免直接承诺未经客户确认的新方案。",
            },
            classification={"case_type": "ORDER_DELIVERY_RISK"},
            **common,
        ),
        Case(
            id="CM-2026-012",
            title="MCU-X7 关键物料供应商交付时间未确认",
            description="供应商尚未提供 MCU-X7 的恢复交付日期，关联订单存在持续扩大的履约风险。",
            status=CaseStatus.OPEN,
            business_payload={
                "customer": "Northstar Mobility",
                "material": "MCU-X7",
                "commitment_due_date": "2026-08-24",
                "risk_level": "HIGH",
            },
            human_proposal=None,
            **common,
        ),
        Case(
            id="CM-2026-015",
            title="MCU-X7B 替代料缺少客户认证与技术验证",
            description="候选替代料 MCU-X7B 尚未完成技术验证和客户认证，暂不能用于履约承诺。",
            status=CaseStatus.OPEN,
            business_payload={
                "customer": "Northstar Mobility",
                "material": "MCU-X7B",
                "commitment_due_date": "2026-08-30",
                "risk_level": "MEDIUM",
            },
            human_proposal=None,
            **common,
        ),
        Case(
            id="CM-2026-009",
            title="华东售后 MCU-X7 备件需求两周内激增",
            description="华东售后中心的 MCU-X7 备件需求在两周内显著上升，需要重新确认库存分配与补货计划。",
            status=CaseStatus.OPEN,
            business_payload={
                "customer": "华东售后中心",
                "material": "MCU-X7",
                "commitment_due_date": "2026-09-02",
                "risk_level": "MEDIUM",
            },
            human_proposal=None,
            **common,
        ),
        Case(
            id="CM-2026-006",
            title="华南仓 MCU-X7 到货数量与系统记录不一致",
            description="华南仓已完成 MCU-X7 实收数量与系统记录差异的复核和闭环。",
            status=CaseStatus.CLOSED,
            business_payload={
                "customer": "华南仓",
                "material": "MCU-X7",
                "commitment_due_date": "2026-08-20",
                "risk_level": "LOW",
            },
            human_proposal=None,
            **common,
        ),
    ]
