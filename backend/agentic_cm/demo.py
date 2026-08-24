from .domain import Case, CaseStatus, OrchestrationPhase


def demo_cases() -> list[Case]:
    classification = {
        "case_type": "ORDER_DELIVERY_RISK",
    }
    primary = Case(
        id="CM-2026-014", title="订单预计延期",
        description="订单 SO-48392 的关键物料预计晚于承诺日期 12 天，可能影响客户交付。",
        status=CaseStatus.OPEN, phase=OrchestrationPhase.INTAKE,
        owner="陈澄", owner_role="订单统筹经理",
        business_payload={
            "order_id": "SO-48392",
            "customer": "Northstar Mobility",
            "material": "MCU-X7",
            "gap_quantity": 18400,
            "target_date": "2026-08-24",
        },
        human_proposal={"revision": 1, "author": "陈澄", "role": "订单统筹经理", "content": "建议优先评估现有认证范围内的替代物料，避免直接承诺未经客户确认的新方案。"},
        classification=classification,
    )
    related = [
        ("CM-2026-012", "供应商交付异常", "OPEN"),
        ("CM-2026-015", "替代料认证缺口", "OPEN"),
        ("CM-2026-009", "备件需求激增", "OPEN"),
        ("CM-2026-006", "华南仓到货差异", "CLOSED"),
    ]
    return [primary] + [
        Case(id=case_id, title=title, description="固定演示 Case", status=CaseStatus(status), phase=OrchestrationPhase.INTAKE, owner="陈澄", owner_role="订单统筹经理", business_payload={}, human_proposal=None)
        for case_id, title, status in related
    ]
