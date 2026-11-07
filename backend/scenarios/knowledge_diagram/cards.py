"""Confirmed claims -> editable cards -> immutable illustrations and PNG/ZIP versions."""

import copy
import hashlib
import os
import re
import tempfile
import time
import zipfile

from .cards_schema import Card
from .image_provider import PRICE_MICRO, ImageProvider
from .render_cards import digest, render
from .repository import DomainError, uid


def basis(work):
    return digest({"source": work["sources"][-1], "claims": work["claims"]})


def current(work):
    return work.get("cards_basis") == basis(work) and work["stage"] == "reviewed"


def fingerprint(work):
    return digest({"basis": work.get("cards_basis"), "cards": work.get("cards", [])})


def atomic_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Cards:
    def __init__(self, service, provider=None):
        self.service, self.repo = service, service.repo
        self.provider = provider or ImageProvider()

    def path(self, work_id, filename):
        self.repo.path(work_id)  # validate even for missing assets
        if not re.fullmatch(r"[a-f0-9]{32}\.(png|zip)", filename):
            raise DomainError("NOT_FOUND", "文件不存在", 404)
        return self.repo.root / "assets" / work_id / filename

    def checked(self, work):
        if not work.get("cards") or not current(work):
            raise DomainError(
                "REVIEW_REQUIRED", "请先完成知识核对，再重新编排卡片；已有图片版本仍保留", 409
            )

    def card(self, work, card_id):
        card = next((c for c in work.get("cards", []) if c["id"] == card_id), None)
        if not card:
            raise DomainError("NOT_FOUND", "卡片不存在", 404)
        return card

    def draft(self, work_id, request):
        def change(work):
            claims = [c for c in work["claims"] if c["active"]]
            if work["stage"] != "reviewed" or not all(c["confirmed"] for c in claims):
                raise DomainError("REVIEW_REQUIRED", "请先确认全部知识点", 409)
            if not 3 <= len(claims) <= 6:
                raise DomainError("CARD_COUNT", "请保留3至6个已确认知识点后编排卡片", 422)
            if work.get("cards"):
                work.setdefault("card_history", []).append(copy.deepcopy(work["cards"]))
            work["cards"] = [
                Card(
                    id=uid(),
                    claim_id=c["id"],
                    title=f"知识点 {i + 1:02d}",
                    body=c["text"],
                    narration=c["text"],
                    prompt=c["text"],
                    kind=c["kind"],
                ).model_dump()
                for i, c in enumerate(claims)
            ]
            work["cards_basis"] = basis(work)

        return self.repo.mutate(work_id, request.expected_revision, change)

    def edit(self, work_id, card_id, request):
        def change(work):
            self.checked(work)
            card = self.card(work, card_id)
            values = request.model_dump(exclude={"expected_revision"})
            updated = {**card, **values}
            if updated == card:
                return
            work.setdefault("card_history", []).append(copy.deepcopy(work["cards"]))
            if values["prompt"] != card["prompt"]:
                updated["illustration_id"] = None  # keep previous illustration in immutable history
            if values["body"] != card["body"] or values["title"] != card["title"]:
                updated["edited"] = True
            card.update(Card.model_validate(updated).model_dump())

        return self.repo.mutate(work_id, request.expected_revision, change)

    def order(self, work_id, request):
        def change(work):
            self.checked(work)
            old = {c["id"]: c for c in work["cards"]}
            if len(request.card_ids) != len(old) or set(request.card_ids) != set(old):
                raise DomainError("CARD_ORDER", "排序须包含全部卡片且不能重复", 422)
            work.setdefault("card_history", []).append(copy.deepcopy(work["cards"]))
            work["cards"] = [old[cid] for cid in request.card_ids]

        return self.repo.mutate(work_id, request.expected_revision, change)

    def start(self, work_id, request, kind, card_id=None, submit=True):
        work = self.repo.get(work_id)
        previous = next(
            (j for j in work["jobs"] if j["operation_id"] == request.operation_id), None
        )
        if previous:
            if previous.get("kind", "extract") != kind or previous.get("card_id") != card_id:
                raise DomainError("OPERATION_CONFLICT", "此操作编号已用于其他任务", 409)
            return self.service.job(work_id, previous["id"])
        self.checked(work)
        if kind == "illustration":
            self.provider.ready()
            self.provider.prompt(self.card(work, card_id)["prompt"])
            if request.max_cost_micro < PRICE_MICRO:
                raise DomainError("COST_CONFIRMATION", "本张图片费用上限不足，未提交", 409)
        job_id = uid()

        def change(value):
            self.checked(value)
            if any(j["operation_id"] == request.operation_id for j in value["jobs"]):
                raise DomainError("DUPLICATE_OPERATION", "任务已提交，请刷新查看", 409)
            if any(j["status"] in {"pending", "running"} for j in value["jobs"]):
                raise DomainError("JOB_RUNNING", "请等待当前任务结束", 409)
            if kind == "illustration":
                from .service import budget

                if any(
                    e["status"] == "uncertain" or e.get("accounting_error")
                    for e in value["budget_entries"]
                ):
                    raise DomainError(
                        "ACCOUNTING_UNCERTAIN", "上一调用的结果或费用待核对，已暂停新生图", 409
                    )
                if budget(value)["available_micro"] < PRICE_MICRO + 220_000:
                    raise DomainError(
                        "BUDGET_INSUFFICIENT", "剩余预算不足，需保留配音及安全余量", 409
                    )
                if sum(j.get("kind") == "illustration" for j in value["jobs"]) >= 8:
                    raise DomainError("ATTEMPT_LIMIT", "本套图片调用次数已到上限", 409)
                value["budget_entries"].append(
                    {
                        "job_id": job_id,
                        "status": "reserved",
                        "reserved_micro": PRICE_MICRO,
                        "tariff": "wanx2.0-t2i-turbo-beijing-2026-11-07",
                    }
                )
            value["jobs"].append(
                {
                    "id": job_id,
                    "operation_id": request.operation_id,
                    "kind": kind,
                    "card_id": card_id,
                    "status": "pending",
                    "error": None,
                    "snapshot": copy.deepcopy(value["cards"]),
                    "basis": value["cards_basis"],
                    "source_title": value["sources"][-1]["title"],
                    "started": time.time(),
                }
            )

        self.repo.mutate(work_id, request.expected_revision, change)
        if submit:
            self.service.worker.submit(self.run, work_id, job_id)
        return self.service.job(work_id, job_id)

    def run(self, work_id, job_id):
        def begin(work):
            job = next(j for j in work["jobs"] if j["id"] == job_id)
            if job["status"] != "pending":
                raise DomainError("JOB_NOT_PENDING", "任务已执行或中断", 409)
            job["status"] = "running"

        try:
            work = self.repo.mutate(work_id, None, begin)
        except DomainError:
            return
        job = next(j for j in work["jobs"] if j["id"] == job_id)
        try:
            if job["kind"] == "illustration":
                self.generate(work_id, job)
            else:
                self.export(work_id, job)
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, DomainError)
                else DomainError(
                    "CARD_GENERATION_FAILED", "图片处理未完成，已有内容及任务记录已保留", 502
                )
            )

            def fail(value):
                item = next(j for j in value["jobs"] if j["id"] == job_id)
                item.update(status="failed", error={"code": error.code, "message": error.message})
                for entry in value["budget_entries"]:
                    if entry["job_id"] == job_id and entry["status"] != "settled":
                        entry["status"] = "uncertain"

            self.repo.mutate(work_id, None, fail)

    def generate(self, work_id, job):
        card = next(c for c in job["snapshot"] if c["id"] == job["card_id"])
        task_id = self.provider.submit(card["prompt"])

        def submitted(value):
            next(j for j in value["jobs"] if j["id"] == job["id"])["remote_task_id"] = task_id

        self.repo.mutate(work_id, None, submitted)  # persist before any polling
        self.collect(work_id, job, task_id, card)

    def collect(self, work_id, job, task_id, card):
        result = self.provider.wait(task_id)

        def settle(value):
            entry = next(e for e in value["budget_entries"] if e["job_id"] == job["id"])
            entry.update(
                status="settled",
                actual_micro=PRICE_MICRO,
                image_count=1,
                request_id=result["request_id"],
                duration=round(time.time() - job["started"], 3),
            )

        self.repo.mutate(
            work_id, None, settle
        )  # successful generation costs money even if download fails
        content = self.provider.download(result["url"])
        image_id = uid()
        filename = image_id + ".png"
        atomic_bytes(self.path(work_id, filename), content)
        illustration = {
            "id": image_id,
            "card_id": card["id"],
            "prompt": card["prompt"],
            "sha256": hashlib.sha256(content).hexdigest(),
            "filename": filename,
            "model": self.provider.model,
        }

        def complete(value):
            value.setdefault("illustrations", []).append(illustration)
            target = next((c for c in value.get("cards", []) if c["id"] == card["id"]), None)
            fresh = (
                current(value)
                and value["cards_basis"] == job["basis"]
                and target
                and target["prompt"] == card["prompt"]
            )
            if fresh:
                target["illustration_id"] = image_id
            next(j for j in value["jobs"] if j["id"] == job["id"])["status"] = (
                "completed" if fresh else "stale"
            )

        self.repo.mutate(work_id, None, complete)

    def resume(self, work_id, job_id, request):
        # Only poll a known task, no new paid submission; retain uncertain reservation.
        def change(work):
            job = next((j for j in work["jobs"] if j["id"] == job_id), None)
            if not job or job.get("kind") != "illustration" or not job.get("remote_task_id"):
                raise DomainError("NO_REMOTE_TASK", "没有可核对的远程任务，请先核对供应商记录", 409)
            if job["status"] not in {"failed", "interrupted"}:
                raise DomainError("JOB_NOT_RESUMABLE", "此任务无需恢复", 409)
            self.provider.ready()
            job.update(status="running", error=None)

        work = self.repo.mutate(work_id, request.expected_revision, change)
        job = next(j for j in work["jobs"] if j["id"] == job_id)

        def run_resume():
            try:
                card = next(c for c in job["snapshot"] if c["id"] == job["card_id"])
                self.collect(work_id, job, job["remote_task_id"], card)
            except Exception:

                def fail(value):
                    item = next(j for j in value["jobs"] if j["id"] == job_id)
                    item.update(
                        status="failed",
                        error={"code": "IMAGE_UNCERTAIN", "message": "原任务仍待核对，未重新生图"},
                    )

                self.repo.mutate(work_id, None, fail)

        self.service.worker.submit(run_resume)
        return self.service.job(work_id, job_id)

    def export(self, work_id, job):
        work = self.repo.get(work_id)
        images = {i["id"]: i for i in work.get("illustrations", [])}
        files, outputs = [], []
        for index, card in enumerate(job["snapshot"], 1):
            illustration = images.get(card["illustration_id"])
            path = self.path(work_id, illustration["filename"]) if illustration else None
            if path and hashlib.sha256(path.read_bytes()).hexdigest() != illustration["sha256"]:
                raise DomainError("ASSET_DAMAGED", "插图文件校验不一致，请先恢复原文件", 503)
            outputs.append(
                render(
                    card,
                    path,
                    index,
                    len(job["snapshot"]),
                    job["source_title"],
                    "离线测试插图"
                    if illustration and illustration.get("model", "").startswith("offline-")
                    else "AI 生成插图",
                )
            )
        # No assets committed until every card passes overflow/glyph/image validation.
        for content in outputs:
            filename = uid() + ".png"
            atomic_bytes(self.path(work_id, filename), content)
            files.append(filename)
        zip_name = uid() + ".zip"
        import io

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for i, content in enumerate(outputs, 1):
                archive.writestr(f"{i:02d}.png", content)
        atomic_bytes(self.path(work_id, zip_name), buffer.getvalue())
        version = {
            "id": uid(),
            "fingerprint": digest({"basis": job["basis"], "cards": job["snapshot"]}),
            "cards": job["snapshot"],
            "files": files + [zip_name],
        }

        def complete(value):
            value.setdefault("exports", []).append(version)
            fresh = current(value) and fingerprint(value) == version["fingerprint"]
            next(j for j in value["jobs"] if j["id"] == job["id"])["status"] = (
                "completed" if fresh else "stale"
            )

        self.repo.mutate(work_id, None, complete)

    def download(self, work_id, version_id, number):
        work = self.repo.get(work_id)
        version = next((v for v in work.get("exports", []) if v["id"] == version_id), None)
        if not version:
            raise DomainError("NOT_FOUND", "图片版本不存在", 404)
        if number == "all.zip":
            filename, name = version["files"][-1], "知识图解.zip"
        elif re.fullmatch(r"0[1-6]\.png", number) and int(number[:2]) <= len(version["cards"]):
            filename, name = version["files"][int(number[:2]) - 1], number
        else:
            raise DomainError("NOT_FOUND", "文件不存在", 404)
        path = self.path(work_id, filename)
        if not path.is_file():
            raise DomainError("ASSET_MISSING", "此版本文件丢失，版本记录仍保留", 404)
        return path, name
