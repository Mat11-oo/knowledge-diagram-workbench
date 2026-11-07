"""Editable, bounded animation storyboards. No model calls or media production."""

import copy
from typing import Literal

from pydantic import Field, field_validator

from .cards import current, fingerprint
from .contracts import StrictModel, Versioned
from .repository import DomainError, uid


class Step(StrictModel):
    label: str = Field(min_length=1, max_length=24)
    detail: str = Field(max_length=160)


class Scene(StrictModel):
    id: str
    claim_id: str
    card_id: str
    title: str = Field(min_length=1, max_length=60)
    template: Literal["flow", "relation", "compare"]
    narration: str = Field(min_length=1, max_length=1000)
    steps: list[Step] = Field(min_length=2, max_length=5)
    confirmed: bool = False

    @field_validator("title", "narration")
    @classmethod
    def visible(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value


class SceneEdit(Versioned):
    title: str = Field(min_length=1, max_length=60)
    template: Literal["flow", "relation", "compare"]
    narration: str = Field(min_length=1, max_length=1000)
    steps: list[Step] = Field(min_length=2, max_length=5)


class Scenes:
    def __init__(self, repo):
        self.repo = repo

    @staticmethod
    def checked(work):
        if not current(work) or work.get("scenes_basis") != fingerprint(work):
            raise DomainError(
                "STORYBOARD_STALE", "知识或卡片已变化，请重新准备分镜；旧分镜已保留", 409
            )

    @staticmethod
    def get_scene(work, scene_id):
        scene = next((s for s in work.get("scenes", []) if s["id"] == scene_id), None)
        if scene is None:
            raise DomainError("NOT_FOUND", "分镜不存在", 404)
        return scene

    def draft(self, work_id, request):
        def change(work):
            if not current(work) or not work.get("cards"):
                raise DomainError("REVIEW_REQUIRED", "请先完成知识点核对并编排卡片", 409)
            if work.get("scenes"):
                work.setdefault("scene_history", []).append(copy.deepcopy(work["scenes"]))
            # Honest empty planning scaffold: no fabricated relationships or AI analysis.
            work["scenes"] = [
                Scene(
                    id=uid(),
                    claim_id=c["claim_id"],
                    card_id=c["id"],
                    title=c["title"],
                    template="relation",
                    narration=c["narration"],
                    steps=[
                        Step(label="对象一", detail=""),
                        Step(label="关联说明", detail=""),
                        Step(label="对象二", detail=""),
                    ],
                ).model_dump()
                for c in work["cards"]
            ]
            work["scenes_basis"] = fingerprint(work)

        return self.repo.mutate(work_id, request.expected_revision, change)

    def edit(self, work_id, scene_id, request):
        def change(work):
            self.checked(work)
            scene = self.get_scene(work, scene_id)
            values = request.model_dump(exclude={"expected_revision"})
            new = Scene.model_validate({**scene, **values, "confirmed": False}).model_dump()
            if all(scene[k] == new[k] for k in values):
                return
            work.setdefault("scene_history", []).append(copy.deepcopy(work["scenes"]))
            scene.update(new)

        return self.repo.mutate(work_id, request.expected_revision, change)

    def confirm(self, work_id, scene_id, request):
        def change(work):
            self.checked(work)
            scene = self.get_scene(work, scene_id)
            if any(
                not step["label"].strip() or not step["detail"].strip() for step in scene["steps"]
            ):
                raise DomainError(
                    "STORYBOARD_INCOMPLETE", "请补齐每一步的对象和讲解内容，再核对确认", 422
                )
            scene["confirmed"] = True

        return self.repo.mutate(work_id, request.expected_revision, change)
