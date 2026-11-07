"""Offline contract and recovery tests. Fake provider is injected ONLY in tests."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from knowledge_app import create_app
from scenarios.knowledge_diagram.provider import Provider, parse_claims
from scenarios.knowledge_diagram.repository import DomainError, Repository
from scenarios.knowledge_diagram.schemas import (
    ClaimEdit,
    ClaimSelection,
    ExtractRequest,
    MergeClaims,
    SaveMaterial,
)
from scenarios.knowledge_diagram.service import Service, budget, public_work

MATERIAL = {
    "title": "公开材料",
    "text": "知识可以整理。引文需要核对。观点可以编辑。内容需要保存。😀图解便于理解。",
    "url": "",
    "audience": "普通读者",
}


class FakeProvider:
    key, model, enabled, pricing_confirmed = "fake-test", "test-double", True, True
    calls = 0

    def ready(self):
        pass

    def reservation(self, source):
        return 100_000

    def extract(self, source):
        self.calls += 1
        phrases = source["text"].split("。")[:4]
        raw = {
            "claims": [
                {"text": t, "kind": "supplement" if i == 3 else "source", "quotes": [t + "。"]}
                for i, t in enumerate(phrases)
            ]
        }
        return {
            "content": json.dumps(raw, ensure_ascii=False),
            "usage": {"prompt_tokens": 100, "completion_tokens": 100},
            "request_id": "mock-offline",
            "duration": 0.1,
        }


@pytest.fixture
def system(tmp_path):
    provider = FakeProvider()
    repo = Repository(tmp_path)
    service = Service(repo, provider)
    work = repo.create(MATERIAL)
    yield repo, service, provider, work
    service.worker.shutdown(wait=True)


def extracted(system):
    repo, service, provider, work = system
    job = service.start_extraction(
        work["id"],
        ExtractRequest(expected_revision=work["revision"], operation_id="op-test-0001"),
        submit=False,
    )
    service.run(work["id"], job["id"])
    return repo.get(work["id"])


def test_api_save_and_validation_no_secret(tmp_path):
    with TestClient(create_app(tmp_path, FakeProvider()), base_url="http://127.0.0.1") as client:
        response = client.post("/api/knowledge/works", json=MATERIAL)
        assert response.status_code == 201
        work_id = response.json()["work"]["id"]
        assert (
            client.get(f"/api/knowledge/works/{work_id}").json()["work"]["sources"][0]["text"]
            == MATERIAL["text"]
        )
        bad = client.post(
            "/api/knowledge/works", json={**MATERIAL, "text": "private-full-doc" * 900}
        )
        assert bad.status_code == 422 and "private-full-doc" not in bad.text


def test_local_boundary(tmp_path):
    with TestClient(create_app(tmp_path, FakeProvider()), base_url="http://127.0.0.1") as client:
        assert (
            client.get(
                "/api/knowledge/works", headers={"origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert (
            client.get("/api/knowledge/works", headers={"host": "evil.example"}).status_code == 403
        )
        assert client.get("/code/data/anything").status_code == 404
        assert client.get("/api/config").status_code == 404


def test_missing_key_stops_before_billing(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    provider = Provider()
    with pytest.raises(DomainError, match="MODEL_NOT_CONFIGURED"):
        provider.ready()


def test_paid_permission_guard(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "fake-test")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_PAID", "0")
    with pytest.raises(DomainError, match="PAID_CALLS_DISABLED"):
        Provider().ready()


def test_unverified_pricing_guard(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "fake-test")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_PAID", "1")
    monkeypatch.setenv("KNOWLEDGE_PRICING_CONFIRMED", "0")
    with pytest.raises(DomainError, match="PRICING_UNVERIFIED"):
        Provider().ready()


def test_extract_uses_usage_and_requires_human(system):
    work = extracted(system)
    assert work["stage"] == "review"
    assert len(work["claims"]) == 4
    assert all(not c["confirmed"] for c in work["claims"])
    assert work["claims"][-1]["kind"] == "supplement"
    assert budget(work)["settled_micro"] == 1000
    assert budget(work)["reserved_micro"] == 0
    assert "budget_entries" not in public_work(work)


def test_confirmation_and_edit_invalidate(system):
    repo, service, _, _ = system
    work = extracted(system)
    work = service.confirm(
        work["id"],
        ClaimSelection(
            expected_revision=work["revision"], claim_ids=[c["id"] for c in work["claims"]]
        ),
    )
    assert work["stage"] == "reviewed"
    work = service.edit(
        work["id"],
        work["claims"][0]["id"],
        ClaimEdit(expected_revision=work["revision"], text="修改后的观点"),
    )
    assert work["stage"] == "review" and not work["claims"][0]["confirmed"]
    assert repo.get(work["id"])["claim_history"]


def test_source_change_requires_new_evidence(system):
    _, service, _, _ = system
    work = extracted(system)
    work = service.save_material(
        work["id"],
        SaveMaterial(**{**MATERIAL, "text": "新的正文。"}, expected_revision=work["revision"]),
    )
    assert len(work["sources"]) == 2
    with pytest.raises(DomainError, match="SOURCE_CHANGED"):
        service.confirm(
            work["id"],
            ClaimSelection(expected_revision=work["revision"], claim_ids=[work["claims"][0]["id"]]),
        )


def test_unicode_reference_is_codepoint():
    source = {"text": "😀甲句。乙句。丙句。丁句。", "revision": 1}
    raw = json.dumps(
        {
            "claims": [
                {"text": x, "kind": "source", "quotes": [x]}
                for x in ["甲句", "乙句", "丙句", "丁句"]
            ]
        }
    )
    claims = parse_claims(raw, source)
    assert claims[0]["references"][0]["start_cp"] == 1


@pytest.mark.parametrize("quote", ["不存在", "重复", ""])
def test_invalid_and_ambiguous_quotes_rejected(quote):
    raw = json.dumps(
        {"claims": [{"text": "观点", "kind": "source", "quotes": [quote]} for _ in range(4)]}
    )
    with pytest.raises(DomainError, match="REFERENCE_INVALID"):
        parse_claims(raw, {"text": "重复重复", "revision": 1})


def test_merge_preserves_quotes_and_supplement(system):
    _, service, _, _ = system
    work = extracted(system)
    work = service.merge(
        work["id"],
        MergeClaims(
            expected_revision=work["revision"],
            claim_ids=[work["claims"][0]["id"], work["claims"][-1]["id"]],
            text="合并后的补充观点",
        ),
    )
    claim = work["claims"][-1]
    assert (
        len(claim["references"]) == 2 and claim["kind"] == "supplement" and not claim["confirmed"]
    )


def test_duplicate_operation_never_double_send(system):
    repo, service, provider, work = system
    request = ExtractRequest(expected_revision=1, operation_id="op-test-0001")
    job = service.start_extraction(work["id"], request, submit=False)
    same = service.start_extraction(work["id"], request, submit=False)
    assert job["id"] == same["id"]
    service.run(work["id"], job["id"])
    service.run(work["id"], job["id"])
    assert provider.calls == 1 and len(repo.get(work["id"])["budget_entries"]) == 1


def test_unknown_result_preserves_budget_after_restart(system):
    repo, service, _, work = system
    job = service.start_extraction(
        work["id"], ExtractRequest(expected_revision=1, operation_id="op-test-0001"), submit=False
    )
    Repository(repo.root).recover()
    restored = repo.get(work["id"])
    assert restored["jobs"][0]["status"] == "interrupted"
    assert budget(restored)["reserved_micro"] == 100_000
    service.run(work["id"], job["id"])
    assert system[2].calls == 0


def test_optimistic_concurrency_protects_data(system):
    repo, service, _, work = system
    service.save_material(
        work["id"], SaveMaterial(**{**MATERIAL, "title": "先保存的标题"}, expected_revision=1)
    )
    with pytest.raises(DomainError, match="REVISION_CONFLICT"):
        service.save_material(work["id"], SaveMaterial(**MATERIAL, expected_revision=1))
    assert repo.get(work["id"])["sources"][-1]["title"] == "先保存的标题"


def test_budget_limit_stops_without_send(system):
    repo, service, provider, work = system

    def spend(value):
        value["budget_entries"].append(
            {"status": "settled", "actual_micro": 950_000, "reserved_micro": 950_000}
        )

    work = repo.mutate(work["id"], 1, spend)
    with pytest.raises(DomainError, match="BUDGET_INSUFFICIENT"):
        service.start_extraction(
            work["id"],
            ExtractRequest(expected_revision=work["revision"], operation_id="op-test-0001"),
            submit=False,
        )
    assert provider.calls == 0


def test_stale_job_does_not_overwrite_new_source(system):
    repo, service, _, work = system
    job = service.start_extraction(
        work["id"], ExtractRequest(expected_revision=1, operation_id="op-test-0001"), submit=False
    )
    work = repo.get(work["id"])
    service.save_material(
        work["id"],
        SaveMaterial(**{**MATERIAL, "text": "已修改正文。"}, expected_revision=work["revision"]),
    )
    service.run(work["id"], job["id"])
    latest = repo.get(work["id"])
    assert not latest["claims"] and latest["jobs"][0]["status"] == "stale"
    assert latest["claim_history"] and budget(latest)["settled_micro"] == 1000


def test_bad_model_output_still_charged(system, monkeypatch):
    _, service, provider, work = system
    monkeypatch.setattr(
        provider,
        "extract",
        lambda source: {
            "content": "invalid",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "request_id": "offline",
            "duration": 0,
        },
    )
    job = service.start_extraction(
        work["id"], ExtractRequest(expected_revision=1, operation_id="op-test-0001"), submit=False
    )
    service.run(work["id"], job["id"])
    latest = service.repo.get(work["id"])
    assert budget(latest)["settled_micro"] == 60 and latest["jobs"][0]["status"] == "failed"


def test_corrupt_file_not_overwritten(system):
    repo, _, _, work = system
    repo.path(work["id"]).write_text("broken private data")
    with pytest.raises(DomainError, match="DATA_DAMAGED"):
        repo.get(work["id"])
    assert repo.path(work["id"]).read_text() == "broken private data"


def test_paths_cannot_escape(system):
    with pytest.raises(DomainError, match="NOT_FOUND"):
        system[0].get("../../private")


def test_racing_writes_do_not_lose_revision(system):
    repo, _, _, work = system

    def write(_):
        try:
            repo.mutate(work["id"], 1, lambda w: None)
            return True
        except DomainError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(write, range(2))) == 1


def test_excess_usage_is_retained_and_blocks_future_calls(system, monkeypatch):
    repo, service, provider, work = system
    monkeypatch.setattr(
        provider,
        "extract",
        lambda source: {
            "content": "",
            "usage": {"prompt_tokens": 60_000, "completion_tokens": 0},
            "request_id": "offline",
            "duration": 0,
        },
    )
    job = service.start_extraction(
        work["id"], ExtractRequest(expected_revision=1, operation_id="op-test-0001"), submit=False
    )
    service.run(work["id"], job["id"])
    latest = repo.get(work["id"])
    assert budget(latest)["reserved_micro"] == 120_000
    with pytest.raises(DomainError, match="ACCOUNTING_UNCERTAIN"):
        service.start_extraction(
            work["id"],
            ExtractRequest(expected_revision=latest["revision"], operation_id="op-test-0002"),
            submit=False,
        )


def test_api_extraction_confirmation_and_reopen(tmp_path):
    import time

    with TestClient(create_app(tmp_path, FakeProvider()), base_url="http://127.0.0.1") as client:
        work = client.post("/api/knowledge/works", json=MATERIAL).json()["work"]
        prefix = f"/api/knowledge/works/{work['id']}"
        started = client.post(
            prefix + "/extract", json={"expected_revision": 1, "operation_id": "api-offline-01"}
        )
        assert started.status_code == 202
        for _ in range(100):
            work = client.get(prefix).json()["work"]
            if work["jobs"][-1]["status"] == "completed":
                break
            time.sleep(0.01)
        assert len(work["claims"]) == 4
        assert "source" not in work["jobs"][0]
        result = client.post(
            prefix + "/confirm",
            json={
                "expected_revision": work["revision"],
                "claim_ids": [c["id"] for c in work["claims"]],
            },
        )
        assert result.json()["work"]["stage"] == "reviewed"
    with TestClient(create_app(tmp_path, FakeProvider()), base_url="http://127.0.0.1") as restored:
        work = restored.get(prefix).json()["work"]
        assert all(c["confirmed"] for c in work["claims"])
        assert work["budget"]["settled_micro"] == 1000


def test_provider_transport_is_single_send_and_safe(monkeypatch):
    import httpx

    import scenarios.knowledge_diagram.provider as module

    for name, value in {
        "MODEL_API_KEY": "fake-test",
        "KNOWLEDGE_ALLOW_PAID": "1",
        "KNOWLEDGE_PRICING_CONFIRMED": "1",
        "MODEL_BASE_URL": "https://api.deepseek.com",
        "MODEL_NAME": "deepseek-flash",
    }.items():
        monkeypatch.setenv(name, value)
    calls = []
    real_client = httpx.Client

    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "test-call",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(transport), **kwargs),
    )
    result = module.Provider().extract(MATERIAL)
    assert len(calls) == 1 and calls[0]["thinking"]["type"] == "disabled"
    assert calls[0]["max_tokens"] == 4000 and result["usage"]["prompt_tokens"] == 1


def test_interrupted_reservation_blocks_duplicate_charge(system):
    repo, service, _, work = system
    service.start_extraction(
        work["id"], ExtractRequest(expected_revision=1, operation_id="op-test-0001"), submit=False
    )
    repo.recover()
    current = repo.get(work["id"])
    with pytest.raises(DomainError, match="ACCOUNTING_UNCERTAIN"):
        service.start_extraction(
            work["id"],
            ExtractRequest(expected_revision=current["revision"], operation_id="op-test-0002"),
            submit=False,
        )


def test_valid_json_with_damaged_schema_is_preserved(system):
    repo, _, _, work = system
    path = repo.path(work["id"])
    damaged = json.dumps({"schema_version": 1, "id": work["id"]})
    path.write_text(damaged)
    with pytest.raises(DomainError, match="DATA_DAMAGED"):
        repo.get(work["id"])
    assert path.read_text() == damaged
