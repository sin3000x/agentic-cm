from agentic_cm.service import AuthorizationError
from conftest import DEMO_CASE_ID, OWNER, OWNER_ACTOR, OWNER_ROLE, make_service, orchestrate

NON_OWNER = {"actor": "王淼", "role": "主计划"}


def test_manifest_is_owner_only(tmp_path) -> None:
    service = make_service(tmp_path)
    orchestrate(service)

    owner_view = service.get_case_view(DEMO_CASE_ID, actor=OWNER_ACTOR, role=OWNER_ROLE)
    other_view = service.get_case_view(DEMO_CASE_ID, actor="王淼", role="主计划")
    assert owner_view["manifest"] is not None
    assert owner_view["permissions"]["can_approve_manifest"] is True
    assert other_view["manifest"] is None
    assert other_view["permissions"]["can_view_manifest"] is False
    assert other_view["workflow_paths"] == []

    try:
        service.approve_manifest(DEMO_CASE_ID, ["PATH-01"], actor="王淼", role="主计划")
    except AuthorizationError:
        pass
    else:
        raise AssertionError("a non-owner must not approve the Manifest")
    assert service.get_case(DEMO_CASE_ID).phase.value == "MANIFEST_REVIEW"


def test_manifest_http_endpoints_enforce_owner_boundary(client) -> None:
    owner = dict(OWNER)
    assert client.post(f"/api/cases/{DEMO_CASE_ID}/orchestrate", json=owner).status_code == 200
    other_view = client.get(f"/api/cases/{DEMO_CASE_ID}", params=NON_OWNER)
    assert other_view.status_code == 200
    assert other_view.json()["manifest"] is None

    for method, path, payload in (
        ("get", f"/api/cases/{DEMO_CASE_ID}/manifest", None),
        ("get", f"/api/cases/{DEMO_CASE_ID}/agent-runs", None),
        ("post", f"/api/cases/{DEMO_CASE_ID}/paths/PATH-01/execute", dict(NON_OWNER)),
        ("post", f"/api/cases/{DEMO_CASE_ID}/synthesize", dict(NON_OWNER)),
        (
            "post",
            f"/api/cases/{DEMO_CASE_ID}/manifest/approve",
            {"selected_path_ids": ["PATH-01"], **NON_OWNER},
        ),
    ):
        response = (
            client.get(path, params=NON_OWNER)
            if method == "get"
            else client.post(path, json=payload)
        )
        assert response.status_code == 403, f"{method.upper()} {path} must reject a non-owner"
    assert client.get(f"/api/cases/{DEMO_CASE_ID}/manifest", params=owner).status_code == 200
