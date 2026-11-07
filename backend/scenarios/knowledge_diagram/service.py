import copy
from concurrent.futures import ThreadPoolExecutor

from .provider import parse_claims
from .repository import DomainError, uid

BUDGET_MICRO = 1_000_000


def budget(work):
    settled = sum(
        e.get("actual_micro", 0) for e in work["budget_entries"] if e["status"] == "settled"
    )
    reserved = sum(e["reserved_micro"] for e in work["budget_entries"] if e["status"] != "settled")
    return {
        "limit_micro": BUDGET_MICRO,
        "settled_micro": settled,
        "reserved_micro": reserved,
        "available_micro": max(0, BUDGET_MICRO - settled - reserved),
    }


def public_work(work):
    value = copy.deepcopy(work)
    value["budget"] = budget(value)
    # Input snapshots and raw accounting remain private, not part of UI responses.
    value["jobs"] = [
        {k: v for k, v in job.items() if k in {"id", "operation_id", "status", "error", "kind"}}
        for job in value["jobs"]
    ]
    from .cards import current, fingerprint

    value["cards_current"] = current(value)
    value["deck_fingerprint"] = fingerprint(value)
    value.pop("budget_entries", None)
    return value


class Service:
    def __init__(self, repository, provider):
        self.repo, self.provider = repository, provider
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge")

    def save_material(self, work_id, request):
        def change(work):
            old = work["sources"][-1]
            material = request.model_dump(exclude={"expected_revision"})
            if all(old[key] == value for key, value in material.items()):
                return
            work["sources"].append(dict(material, revision=old["revision"] + 1))
            for claim in work["claims"]:
                claim["confirmed"] = False
            work["stage"] = "review_required" if work["claims"] else "material"

        return self.repo.mutate(work_id, request.expected_revision, change)

    def start_extraction(self, work_id, request, submit=True):
        existing = self.repo.get(work_id)
        previous = next(
            (j for j in existing["jobs"] if j["operation_id"] == request.operation_id), None
        )
        if previous:
            if previous.get("kind", "extract") != "extract":
                raise DomainError("OPERATION_CONFLICT", "此操作编号已用于其他任务", 409)
            return previous
        self.provider.ready()
        job_id = uid()

        def change(work):
            if any(j["operation_id"] == request.operation_id for j in work["jobs"]):
                raise DomainError("DUPLICATE_OPERATION", "该操作已提交，请刷新查看任务", 409)
            if any(j["status"] in {"pending", "running"} for j in work["jobs"]):
                raise DomainError("JOB_RUNNING", "当前作品已有提取任务，请等它结束", 409)
            if any(
                e["status"] == "uncertain" or e.get("accounting_error")
                for e in work["budget_entries"]
            ):
                raise DomainError(
                    "ACCOUNTING_UNCERTAIN", "上一请求的结果或费用仍待核对，已暂停新调用", 409
                )
            if sum(j.get("kind", "extract") == "extract" for j in work["jobs"]) >= 2:
                raise DomainError("ATTEMPT_LIMIT", "本套提取次数已到上限，请先核对现有结果", 409)
            source = copy.deepcopy(work["sources"][-1])
            reserved = self.provider.reservation(source)
            # Leave 0.20 yuan buffer and 0.36 for the later image/audio stages.
            if reserved <= 0 or reserved + 560_000 > budget(work)["available_micro"]:
                raise DomainError(
                    "BUDGET_INSUFFICIENT", "本次提取预计超出可用预算，已停止，材料仍保留", 409
                )
            work["budget_entries"].append(
                {
                    "job_id": job_id,
                    "status": "reserved",
                    "reserved_micro": reserved,
                    "tariff": "deepseek-flash-2026-11-06-peak",
                }
            )
            work["jobs"].append(
                {
                    "id": job_id,
                    "operation_id": request.operation_id,
                    "status": "pending",
                    "source": source,
                    "error": None,
                }
            )

        self.repo.mutate(work_id, request.expected_revision, change)
        if submit:
            self.worker.submit(self.run, work_id, job_id)
        return self.job(work_id, job_id)

    def job(self, work_id, job_id):
        work = public_work(self.repo.get(work_id))
        job = next((j for j in work["jobs"] if j["id"] == job_id), None)
        if job is None:
            raise DomainError("NOT_FOUND", "任务不存在", 404)
        return job

    def run(self, work_id, job_id):
        def begin(work):
            job = next(j for j in work["jobs"] if j["id"] == job_id)
            if job["status"] != "pending":
                raise DomainError("JOB_NOT_PENDING", "该任务已执行或中断", 409)
            job["status"] = "running"

        try:
            work = self.repo.mutate(work_id, None, begin)
        except DomainError:
            return
        source = next(j["source"] for j in work["jobs"] if j["id"] == job_id)
        try:
            result = self.provider.extract(source)
            usage = result["usage"]
            if any(
                type(usage.get(k)) is not int or usage[k] < 0
                for k in ["prompt_tokens", "completion_tokens"]
            ):
                raise DomainError("USAGE_UNKNOWN", "用量无法核对，费用仍预留", 502)
            cost = usage["prompt_tokens"] * 2 + usage["completion_tokens"] * 8

            def settle(work):
                entry = next(e for e in work["budget_entries"] if e["job_id"] == job_id)
                if cost > entry["reserved_micro"]:
                    # Keep the higher liability, block future calls, never hide overshoot.
                    entry["reserved_micro"] = cost
                    entry["status"] = "uncertain"
                    entry["accounting_error"] = True
                    return
                entry.update(
                    status="settled",
                    actual_micro=cost,
                    usage=usage,
                    request_id=result["request_id"],
                    duration=result["duration"],
                )

            settled = self.repo.mutate(work_id, None, settle)
            if any(e.get("accounting_error") for e in settled["budget_entries"]):
                raise DomainError("USAGE_EXCEEDS_RESERVE", "计量超过预留，已暂停后续调用", 502)
            claims = parse_claims(result["content"], source)

            def complete(work):
                job = next(j for j in work["jobs"] if j["id"] == job_id)
                if source["revision"] != work["sources"][-1]["revision"]:
                    work["claim_history"].append(
                        {"source_revision": source["revision"], "claims": claims}
                    )
                    job["status"] = "stale"
                    return
                if work["claims"]:
                    work["claim_history"].append({"claims": work["claims"]})
                work["claims"] = claims
                work["stage"] = "review"
                job["status"] = "completed"

            self.repo.mutate(work_id, None, complete)
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, DomainError)
                else DomainError("GENERATION_FAILED", "提取未完成，已保留材料及费用记录", 502)
            )

            def fail(work):
                job = next(j for j in work["jobs"] if j["id"] == job_id)
                job.update(status="failed", error={"code": error.code, "message": error.message})
                for entry in work["budget_entries"]:
                    if entry["job_id"] == job_id and entry["status"] != "settled":
                        entry["status"] = "uncertain"

            self.repo.mutate(work_id, None, fail)

    @staticmethod
    def claim(work, claim_id):
        claim = next((c for c in work["claims"] if c["id"] == claim_id and c["active"]), None)
        if claim is None:
            raise DomainError("NOT_FOUND", "知识点不存在", 404)
        return claim

    def edit(self, work_id, claim_id, request):
        def change(work):
            claim = self.claim(work, claim_id)
            work["claim_history"].append({"claims": [copy.deepcopy(claim)]})
            claim.update(text=request.text, confirmed=False)
            work["stage"] = "review"

        return self.repo.mutate(work_id, request.expected_revision, change)

    def confirm(self, work_id, request):
        def change(work):
            for claim_id in request.claim_ids:
                claim = self.claim(work, claim_id)
                source = work["sources"][-1]
                for ref in claim["references"]:
                    if (
                        ref["source_revision"] != source["revision"]
                        or source["text"][ref["start_cp"] : ref["end_cp"]] != ref["quote"]
                    ):
                        raise DomainError(
                            "SOURCE_CHANGED", "原文已修改，此知识点须重新提取和核对", 409
                        )
                claim["confirmed"] = True
            active = [c for c in work["claims"] if c["active"]]
            work["stage"] = (
                "reviewed" if active and all(c["confirmed"] for c in active) else "review"
            )

        return self.repo.mutate(work_id, request.expected_revision, change)

    def remove(self, work_id, claim_id, request):
        def change(work):
            self.claim(work, claim_id)["active"] = False
            active = [c for c in work["claims"] if c["active"]]
            work["stage"] = (
                "reviewed" if active and all(c["confirmed"] for c in active) else "review"
            )

        return self.repo.mutate(work_id, request.expected_revision, change)

    def merge(self, work_id, request):
        def change(work):
            if len(set(request.claim_ids)) < 2:
                raise DomainError("MERGE_SELECTION", "请至少选择两个不同的知识点")
            selected = [self.claim(work, cid) for cid in dict.fromkeys(request.claim_ids)]
            refs = []
            for c in selected:
                for ref in c["references"]:
                    if ref not in refs:
                        refs.append(copy.deepcopy(ref))
                c["active"] = False
            work["claims"].append(
                {
                    "id": uid(),
                    "text": request.text,
                    "kind": "supplement"
                    if any(c["kind"] == "supplement" for c in selected)
                    else "source",
                    "references": refs,
                    "confirmed": False,
                    "active": True,
                }
            )
            work["stage"] = "review"

        return self.repo.mutate(work_id, request.expected_revision, change)
