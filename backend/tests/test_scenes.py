"""Storyboard editing only: no image, speech, animation or video generation."""

import pytest
from fastapi.testclient import TestClient
from test_knowledge import MATERIAL, FakeProvider, extracted, system  # noqa: F401

from knowledge_app import create_app
from scenarios.knowledge_diagram.cards import Cards
from scenarios.knowledge_diagram.contracts import Versioned
from scenarios.knowledge_diagram.repository import DomainError, Repository
from scenarios.knowledge_diagram.scenes import SceneEdit, Scenes
from scenarios.knowledge_diagram.schemas import ClaimSelection, SaveMaterial


@pytest.fixture
def storyboard(request):
    environment = request.getfixturevalue("system")
    repo, service, provider, _ = environment
    work = extracted(environment)
    work = service.confirm(
        work["id"],
        ClaimSelection(
            expected_revision=work["revision"], claim_ids=[c["id"] for c in work["claims"]]
        ),
    )
    work = Cards(service).draft(work["id"], Versioned(expected_revision=work["revision"]))
    return Scenes(repo), work, service


def populated(work):
    scene = work["scenes"][0]
    return SceneEdit(
        expected_revision=work["revision"],
        title=scene["title"],
        template="flow",
        narration=scene["narration"],
        steps=[
            {"label": "查看原文", "detail": "定位这条知识点对应的原文。"},
            {"label": "核对观点", "detail": "对照含义以后，再由用户确认。"},
        ],
    )


def test_draft_is_explicitly_incomplete_and_reopenable(storyboard):
    scenes, work, _ = storyboard
    work = scenes.draft(work["id"], Versioned(expected_revision=work["revision"]))
    assert len(work["scenes"]) == 4 and not any(s["confirmed"] for s in work["scenes"])
    assert all(not step["detail"] for s in work["scenes"] for step in s["steps"])
    assert Repository(scenes.repo.root).get(work["id"])["scenes"] == work["scenes"]
    with pytest.raises(DomainError, match="STORYBOARD_INCOMPLETE"):
        scenes.confirm(
            work["id"], work["scenes"][0]["id"], Versioned(expected_revision=work["revision"])
        )


def test_edit_confirm_then_reedit_invalidates_and_preserves_history(storyboard):
    scenes, work, _ = storyboard
    work = scenes.draft(work["id"], Versioned(expected_revision=work["revision"]))
    sid = work["scenes"][0]["id"]
    work = scenes.edit(work["id"], sid, populated(work))
    work = scenes.confirm(work["id"], sid, Versioned(expected_revision=work["revision"]))
    assert work["scenes"][0]["confirmed"]
    change = populated(work)
    change.title = "新的讲解标题"
    work = scenes.edit(work["id"], sid, change)
    assert not work["scenes"][0]["confirmed"] and work["scene_history"][-1][0]["confirmed"]


def test_source_change_rejects_old_storyboard_and_keeps_data(storyboard):
    scenes, work, service = storyboard
    work = scenes.draft(work["id"], Versioned(expected_revision=work["revision"]))
    work = service.save_material(
        work["id"],
        SaveMaterial(**{**MATERIAL, "title": "更改来源"}, expected_revision=work["revision"]),
    )
    with pytest.raises(DomainError, match="STORYBOARD_STALE"):
        scenes.edit(work["id"], work["scenes"][0]["id"], populated(work))
    assert work["scenes"]


def test_revision_conflict_protects_other_edit(storyboard):
    scenes, work, _ = storyboard
    work = scenes.draft(work["id"], Versioned(expected_revision=work["revision"]))
    request = populated(work)
    scenes.edit(work["id"], work["scenes"][0]["id"], request)
    with pytest.raises(DomainError, match="REVISION_CONFLICT"):
        scenes.edit(work["id"], work["scenes"][0]["id"], request)


def test_api_contract_has_no_model_or_media_side_effect(storyboard):
    scenes, work, _ = storyboard
    provider = FakeProvider()
    with TestClient(create_app(scenes.repo.root, provider), base_url="http://127.0.0.1") as client:
        prefix = "/api/knowledge/works/" + work["id"]
        response = client.post(
            prefix + "/scenes/draft", json={"expected_revision": work["revision"]}
        )
        assert response.status_code == 200
        value = response.json()["work"]
        edit = populated(value).model_dump()
        response = client.patch(prefix + "/scenes/" + value["scenes"][0]["id"], json=edit)
        assert response.status_code == 200
        assert provider.calls == 0 and not (scenes.repo.root / "assets").exists()
        assert client.get(prefix).json()["work"]["scenes"][0]["template"] == "flow"
