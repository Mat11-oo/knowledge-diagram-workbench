"""Offline integration evidence; never substitutes for a live image smoke."""

import io
import json
import time
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_knowledge import MATERIAL, FakeProvider

from knowledge_app import create_app
from scenarios.knowledge_diagram.cards import Cards, fingerprint
from scenarios.knowledge_diagram.cards_schema import CardEdit, CardOrder, ImageRequest
from scenarios.knowledge_diagram.image_provider import ImageProvider
from scenarios.knowledge_diagram.repository import DomainError, Repository
from scenarios.knowledge_diagram.schemas import (
    ClaimEdit,
    ClaimSelection,
    ExtractRequest,
    SaveMaterial,
    Versioned,
)
from scenarios.knowledge_diagram.service import Service, budget, public_work


class FakeImages:
    key, enabled, pricing_confirmed, model = "fake-test", True, True, "offline-image-test"

    def __init__(self):
        self.calls = 0

    def ready(self):
        pass

    def prompt(self, text):
        return text

    def submit(self, prompt):
        self.calls += 1
        return "test-remote-01"

    def wait(self, task_id):
        return {"url": "offline", "request_id": "offline-image"}

    def download(self, url):
        output = io.BytesIO()
        Image.new("RGB", (1024, 1024), "#b9cdb3").save(output, "PNG")
        return output.getvalue()


@pytest.fixture
def deck(tmp_path):
    service = Service(Repository(tmp_path), FakeProvider())
    work = service.repo.create(MATERIAL)
    job = service.start_extraction(
        work["id"],
        ExtractRequest(expected_revision=1, operation_id="extract-cards-01"),
        submit=False,
    )
    service.run(work["id"], job["id"])
    work = service.repo.get(work["id"])
    work = service.confirm(
        work["id"],
        ClaimSelection(
            expected_revision=work["revision"], claim_ids=[c["id"] for c in work["claims"]]
        ),
    )
    cards = Cards(service, FakeImages())
    work = cards.draft(work["id"], Versioned(expected_revision=work["revision"]))
    yield cards, work
    service.worker.shutdown(wait=True)


def run_job(cards, work, kind="export", card_id=None, operation="export-cards-01"):
    body = {"expected_revision": work["revision"], "operation_id": operation}
    if kind == "illustration":
        request = ImageRequest(**body, max_cost_micro=40_000)
    else:
        request = ExtractRequest(**body)
    job = cards.start(work["id"], request, kind, card_id, submit=False)
    cards.run(work["id"], job["id"])
    return cards.repo.get(work["id"]), job


def edit_request(work, **changes):
    card = work["cards"][0]
    values = {k: card[k] for k in ("title", "body", "narration", "prompt", "template")}
    return CardEdit(**{**values, **changes}, expected_revision=work["revision"])


def test_unconfirmed_draft_rejected(deck):
    cards, work = deck
    work = cards.service.edit(
        work["id"],
        work["claims"][0]["id"],
        ClaimEdit(expected_revision=work["revision"], text="需重新确认"),
    )
    with pytest.raises(DomainError, match="REVIEW_REQUIRED"):
        cards.draft(work["id"], Versioned(expected_revision=work["revision"]))
    assert not public_work(work)["cards_current"]


def test_text_edit_reuses_image_prompt_edit_detaches_but_keeps_history(deck):
    cards, work = deck
    work, _ = run_job(cards, work, "illustration", work["cards"][0]["id"], "image-cards-01")
    image = work["illustrations"][0]
    card = work["cards"][0]
    before = cards.path(work["id"], image["filename"]).read_bytes()
    work = cards.edit(work["id"], card["id"], edit_request(work, body="改动正文"))
    assert work["cards"][0]["illustration_id"] == image["id"]
    assert cards.path(work["id"], image["filename"]).read_bytes() == before
    assert work["card_history"][-1][0]["body"] == card["body"]
    work = cards.edit(work["id"], card["id"], edit_request(work, prompt="新的插图主题"))
    assert work["cards"][0]["illustration_id"] is None
    assert work["illustrations"][0] == image


def test_export_zip_dimensions_order_and_immutable_versions(deck):
    cards, work = deck
    work, job = run_job(cards, work)
    assert cards.service.job(work["id"], job["id"])["status"] == "completed"
    version = work["exports"][0]
    path, _ = cards.download(work["id"], version["id"], "all.zip")
    original = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["01.png", "02.png", "03.png", "04.png"]
        for i, name in enumerate(archive.namelist()):
            content = archive.read(name)
            with Image.open(io.BytesIO(content)) as image:
                assert image.size == (1080, 1920)
            assert cards.path(work["id"], version["files"][i]).read_bytes() == content
    assert version["cards"][-1]["kind"] == "supplement"
    assert version["fingerprint"] == fingerprint(work)
    order = list(reversed([c["id"] for c in work["cards"]]))
    work = cards.order(work["id"], CardOrder(expected_revision=work["revision"], card_ids=order))
    assert fingerprint(work) != version["fingerprint"]
    work, _ = run_job(cards, work, operation="export-cards-02")
    assert work["exports"][1]["cards"][0]["id"] == order[0]
    assert path.read_bytes() == original
    assert Repository(cards.repo.root).get(work["id"])["exports"] == work["exports"]


def test_reorder_and_stale_revision_guards(deck):
    cards, work = deck
    ids = [c["id"] for c in work["cards"]]
    for order in [ids[:3], [ids[0]] * 4]:
        with pytest.raises(DomainError, match="CARD_ORDER"):
            cards.order(work["id"], CardOrder(expected_revision=work["revision"], card_ids=order))
    with pytest.raises(DomainError, match="REVISION_CONFLICT"):
        cards.order(work["id"], CardOrder(expected_revision=1, card_ids=ids))


@pytest.mark.parametrize(
    "text,code", [("长" * 1000, "TEXT_OVERFLOW"), ("不能缺字😀", "GLYPH_UNSUPPORTED")]
)
def test_refuse_overflow_and_missing_glyphs_without_partial_export(deck, text, code):
    cards, work = deck
    work = cards.edit(work["id"], work["cards"][0]["id"], edit_request(work, body=text))
    work, _ = run_job(cards, work)
    assert work["jobs"][-1]["error"]["code"] == code
    assert work.get("exports", []) == []
    assert not (cards.repo.root / "assets").exists()


def test_source_change_retains_old_export_but_blocks_new(deck):
    cards, work = deck
    work, _ = run_job(cards, work)
    version = work["exports"][0]
    work = cards.service.save_material(
        work["id"],
        SaveMaterial(**{**MATERIAL, "text": "新的材料。"}, expected_revision=work["revision"]),
    )
    assert not public_work(work)["cards_current"]
    with pytest.raises(DomainError, match="REVIEW_REQUIRED"):
        run_job(cards, work, operation="export-cards-02")
    assert cards.download(work["id"], version["id"], "01.png")[0].exists()


def test_image_idempotency_reservation_and_settlement(deck):
    cards, work = deck
    request = ImageRequest(
        expected_revision=work["revision"], operation_id="image-cards-01", max_cost_micro=40_000
    )
    job = cards.start(work["id"], request, "illustration", work["cards"][0]["id"], submit=False)
    assert budget(cards.repo.get(work["id"]))["reserved_micro"] == 40_000
    assert (
        cards.start(work["id"], request, "illustration", work["cards"][0]["id"], submit=False)["id"]
        == job["id"]
    )
    cards.run(work["id"], job["id"])
    cards.run(work["id"], job["id"])
    assert cards.provider.calls == 1
    work = cards.repo.get(work["id"])
    assert budget(work)["settled_micro"] == 41_000 and budget(work)["reserved_micro"] == 0
    assert work["jobs"][-1]["remote_task_id"] == "test-remote-01"
    assert "snapshot" not in cards.service.job(work["id"], job["id"])


def test_budget_and_authorization_stop_before_network(deck):
    cards, work = deck
    request = ImageRequest(
        expected_revision=work["revision"], operation_id="image-cards-01", max_cost_micro=39_999
    )
    with pytest.raises(DomainError, match="COST_CONFIRMATION"):
        cards.start(work["id"], request, "illustration", work["cards"][0]["id"])
    work = cards.repo.mutate(
        work["id"],
        work["revision"],
        lambda w: w["budget_entries"].append(
            {"status": "settled", "actual_micro": 800_000, "reserved_micro": 800_000}
        ),
    )
    with pytest.raises(DomainError, match="BUDGET_INSUFFICIENT"):
        run_job(cards, work, "illustration", work["cards"][0]["id"])
    assert cards.provider.calls == 0


def test_restart_preserves_reservation_and_stops_resubmission(deck):
    cards, work = deck
    cards.start(
        work["id"],
        ImageRequest(
            expected_revision=work["revision"], operation_id="image-cards-01", max_cost_micro=40_000
        ),
        "illustration",
        work["cards"][0]["id"],
        submit=False,
    )
    Repository(cards.repo.root).recover()
    work = cards.repo.get(work["id"])
    assert work["jobs"][-1]["status"] == "interrupted" and budget(work)["reserved_micro"] == 40_000
    with pytest.raises(DomainError, match="ACCOUNTING_UNCERTAIN"):
        run_job(cards, work, "illustration", work["cards"][0]["id"], "image-cards-02")
    assert cards.provider.calls == 0


def test_resume_queries_original_task_without_paid_resubmission(deck, monkeypatch):
    cards, work = deck
    original = cards.provider.wait
    monkeypatch.setattr(
        cards.provider,
        "wait",
        lambda task: (_ for _ in ()).throw(DomainError("IMAGE_TIMEOUT", "测试超时")),
    )
    work, job = run_job(cards, work, "illustration", work["cards"][0]["id"], "image-cards-01")
    assert work["jobs"][-1]["status"] == "failed"
    monkeypatch.setattr(cards.provider, "wait", original)
    cards.resume(work["id"], job["id"], Versioned(expected_revision=work["revision"]))
    cards.service.worker.shutdown(wait=True)
    work = cards.repo.get(work["id"])
    assert cards.provider.calls == 1 and work["jobs"][-1]["status"] == "completed"
    assert budget(work)["reserved_micro"] == 0


def test_api_export_reopen_safe_download(deck):
    cards, work = deck
    with TestClient(
        create_app(cards.repo.root, FakeProvider(), FakeImages()), base_url="http://127.0.0.1"
    ) as client:
        prefix = "/api/knowledge/works/" + work["id"]
        response = client.post(
            prefix + "/exports",
            json={"expected_revision": work["revision"], "operation_id": "api-card-export"},
        )
        assert response.status_code == 202
        for _ in range(100):
            value = client.get(prefix).json()["work"]
            if value["jobs"][-1]["status"] not in {"pending", "running"}:
                break
            time.sleep(0.05)
        version = value["exports"][0]
        assert client.get(prefix + "/exports/" + version["id"] + "/all.zip").status_code == 200
        assert client.get(prefix + "/exports/" + version["id"] + "/07.png").status_code == 404
        assert client.get(prefix + "/illustrations/nonexistent").status_code == 404
        assert (
            client.get(prefix, headers={"Origin": "https://untrusted.example"}).status_code == 403
        )
        assert "snapshot" not in value["jobs"][-1] and "budget_entries" not in value


def test_transport_single_post_poll_count_and_download_validation(monkeypatch):
    for key, value in {
        "DASHSCOPE_API_KEY": "fake-test",
        "KNOWLEDGE_ALLOW_IMAGES": "1",
        "KNOWLEDGE_IMAGE_PRICING_CONFIRMED": "1",
    }.items():
        monkeypatch.setenv(key, value)
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["parameters"]["n"] == 1 and not body["parameters"]["prompt_extend"]
            return httpx.Response(200, json={"output": {"task_id": "remote-01"}})
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [
                        {
                            "url": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/result.png"
                        }
                    ],
                },
                "usage": {"image_count": 1},
                "request_id": "offline",
            },
        )

    real = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)
    )
    provider = ImageProvider()
    assert provider.wait(provider.submit("一张概念插图"))["request_id"] == "offline"
    assert [r.method for r in requests] == ["POST", "GET"]
    for url in [
        "http://127.0.0.1/a.png",
        "https://evil.example/a.png",
        "https://127.0.0.1/a.png",
        "https://user@bucket.oss-cn-beijing.aliyuncs.com/a.png",
    ]:
        with pytest.raises(DomainError, match="IMAGE_URL_REJECTED"):
            provider.download(url)


def test_transport_timeout_never_retries_submission(monkeypatch):
    for key, value in {
        "DASHSCOPE_API_KEY": "fake-test",
        "KNOWLEDGE_ALLOW_IMAGES": "1",
        "KNOWLEDGE_IMAGE_PRICING_CONFIRMED": "1",
    }.items():
        monkeypatch.setenv(key, value)
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("offline timeout")

    real = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(timeout), **kwargs)
    )
    with pytest.raises(DomainError, match="IMAGE_UNCERTAIN"):
        ImageProvider().submit("插图")
    assert len(calls) == 1
