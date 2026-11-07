"""Persisted sentence synthesis and local rendering. Resume never re-sends a sent sentence."""

import copy
import hashlib
import re
import tempfile
import time
from pathlib import Path

from .cards import atomic_bytes, current, fingerprint
from .render_cards import digest, supported_codepoints
from .repository import DomainError, uid
from .tts_provider import MICRO_PER_CHAR, TTSProvider
from .video_render import normalize, render_video


def split_text(text):
    # All visible characters preserved in order, punctuation included. Short captions <=24 codepoints.
    text = text.strip()
    phrases = re.findall(r"[^。！？；，、\n]+[。！？；，、\n]*|[。！？；，、\n]+", text)
    return [p[i : i + 24] for p in phrases for i in range(0, len(p), 24) if p[i : i + 24].strip()]


class Videos:
    def __init__(self, service, cards, provider=None):
        self.service, self.repo, self.cards = service, service.repo, cards
        self.provider = provider or TTSProvider()

    def path(self, work_id, filename):
        self.repo.path(work_id)
        if not re.fullmatch(r"[a-f0-9]{32}\.(wav|mp4)", filename):
            raise DomainError("NOT_FOUND", "媒体文件不存在", 404)
        return self.repo.root / "assets" / work_id / filename

    def plan(self, work):
        self.cards.checked(work)
        export = next(
            (e for e in reversed(work.get("exports", [])) if e["fingerprint"] == fingerprint(work)),
            None,
        )
        if not export or any(not c["illustration_id"] for c in work["cards"]):
            raise DomainError(
                "IMAGES_REQUIRED", "请先完成全部插图并导出与当前卡片一致的PNG版本", 409
            )
        scenes = work.get("scenes", [])
        if (
            not scenes
            or work.get("scenes_basis") != fingerprint(work)
            or len(scenes) != len(work["cards"])
            or any(not scene.get("confirmed") for scene in scenes)
            or any(
                not step.get("label", "").strip() or not step.get("detail", "").strip()
                for scene in scenes
                for step in scene.get("steps", [])
            )
        ):
            raise DomainError(
                "STORYBOARD_REQUIRED", "请先补全并核对当前版本的全部动态分镜", 409
            )
        scenes_by_card = {scene["card_id"]: scene for scene in scenes}
        count = sum(len(scenes_by_card[c["id"]]["narration"].strip()) for c in work["cards"])
        if not 180 <= count <= 240:
            raise DomainError(
                "NARRATION_LENGTH",
                f"整套旁白需180–240字，目前{count}字；请编辑后保存并重新导出PNG",
                422,
            )
        ranges = supported_codepoints()
        segments = []
        for card in work["cards"]:
            scene = scenes_by_card[card["id"]]
            scene_segments = split_text(scene["narration"])
            if len(scene_segments) < len(scene["steps"]):
                raise DomainError(
                    "STORYBOARD_TIMING", "每段分镜至少需要对应一个旁白短句，请补充分镜旁白", 422
                )
            for segment_index, text in enumerate(scene_segments):
                if any(
                    not c.isspace() and not any(a <= ord(c) <= b for a, b in ranges) for c in text
                ):
                    raise DomainError(
                        "GLYPH_UNSUPPORTED", "旁白含字体不支持的字符，请修改后继续", 422
                    )
                key = digest(
                    {"text": text, "voice": self.provider.voice, "model": self.provider.model}
                )
                asset = next((a for a in work.get("audios", []) if a["key"] == key), None)
                if asset and (
                    not self.path(work["id"], asset["filename"]).is_file()
                    or hashlib.sha256(
                        self.path(work["id"], asset["filename"]).read_bytes()
                    ).hexdigest()
                    != asset["sha256"]
                ):
                    raise DomainError(
                        "AUDIO_DAMAGED",
                        "已完成音频文件丢失或损坏，请恢复备份，不会自动再次配音",
                        503,
                    )
                segments.append(
                    {
                        "id": uid(),
                        "text": text,
                        "card_id": card["id"],
                        "scene_id": scene["id"],
                        "scene_template": scene["template"],
                        "scene_title": scene["title"],
                        "scene_steps": copy.deepcopy(scene["steps"]),
                        "scene_step_index": min(
                            len(scene["steps"]) - 1,
                            segment_index * len(scene["steps"]) // max(1, len(scene_segments)),
                        ),
                        "key": key,
                        "audio_id": asset["id"] if asset else None,
                    }
                )
        # Conservative UTF-8 byte bound; verified returned characters must fit reserved liability.
        for segment in segments:
            segment["reserve_micro"] = (
                0 if segment["audio_id"] else len(segment["text"].encode("utf-8")) * MICRO_PER_CHAR
            )
        reserve = sum(s["reserve_micro"] for s in segments)
        if reserve > 60_000:
            raise DomainError(
                "TTS_RESERVE_LIMIT", "旁白计费上界超过0.06元，请缩短至240字以内后继续", 409
            )
        return {
            "segments": segments,
            "reserve_micro": reserve,
            "characters": count,
            "export": export,
        }

    def public_plan(self, work):
        plan = self.plan(work)
        return {
            "characters": plan["characters"],
            "segments": len(plan["segments"]),
            "uncached_segments": sum(not s["audio_id"] for s in plan["segments"]),
            "reserve_micro": plan["reserve_micro"],
            "voice": self.provider.voice,
            "model": self.provider.model,
        }

    def start(self, work_id, request, submit=True):
        work = self.repo.get(work_id)
        previous = next(
            (j for j in work["jobs"] if j["operation_id"] == request.operation_id), None
        )
        if previous:
            if previous.get("kind") != "video":
                raise DomainError("OPERATION_CONFLICT", "操作编号已被其他任务使用", 409)
            return self.service.job(work_id, previous["id"])
        plan = self.plan(work)
        if plan["reserve_micro"]:
            self.provider.ready()
        if plan["reserve_micro"] > request.max_cost_micro:
            raise DomainError("COST_CONFIRMATION", "本次配音费用预留高于确认上限，未调用", 409)
        job_id = uid()

        def change(value):
            from .service import budget

            if any(j["status"] in {"pending", "running"} for j in value["jobs"]):
                raise DomainError("JOB_RUNNING", "请等待当前任务结束", 409)
            if any(
                e["status"] == "uncertain" or e.get("accounting_error")
                for e in value["budget_entries"]
            ):
                raise DomainError(
                    "ACCOUNTING_UNCERTAIN", "上一请求结果或费用待核对，暂停新配音", 409
                )
            if budget(value)["available_micro"] < plan["reserve_micro"] + 200_000:
                raise DomainError(
                    "BUDGET_INSUFFICIENT", "配音后需保留0.20元安全余量，预算不足", 409
                )
            if sum(j.get("kind") == "video" for j in value["jobs"]) >= 3:
                raise DomainError("ATTEMPT_LIMIT", "本套视频更新次数已到上限", 409)
            for segment in plan["segments"]:
                if segment["reserve_micro"]:
                    value["budget_entries"].append(
                        {
                            "job_id": job_id,
                            "segment_id": segment["id"],
                            "reserved_micro": segment["reserve_micro"],
                            "status": "reserved",
                            "sent": False,
                        }
                    )
            value["jobs"].append(
                {
                    "id": job_id,
                    "operation_id": request.operation_id,
                    "kind": "video",
                    "status": "pending",
                    "error": None,
                    "segments": copy.deepcopy(plan["segments"]),
                    "export_snapshot": copy.deepcopy(plan["export"]),
                    "fingerprint": fingerprint(value),
                    "scenes_basis": value.get("scenes_basis", ""),
                    "scenes_fingerprint": digest(value.get("scenes", [])),
                    "model": self.provider.model,
                    "voice": self.provider.voice,
                    "started": time.time(),
                }
            )

        self.repo.mutate(work_id, request.expected_revision, change)
        if submit:
            self.service.worker.submit(self.run, work_id, job_id)
        return self.service.job(work_id, job_id)

    def resume(self, work_id, job_id, request):
        def change(value):
            job = next((j for j in value["jobs"] if j["id"] == job_id), None)
            if (
                not job
                or job.get("kind") != "video"
                or job["status"] not in {"failed", "interrupted"}
            ):
                raise DomainError("JOB_NOT_RESUMABLE", "此视频任务不能恢复", 409)
            if any(
                e["job_id"] == job_id and e["status"] == "uncertain"
                for e in value["budget_entries"]
            ):
                raise DomainError(
                    "ACCOUNTING_UNCERTAIN", "有一句配音结果未知，须先核对供应商；不会重发", 409
                )
            if any(not s["audio_id"] and not s.get("result") for s in job["segments"]):
                self.provider.ready()
            job.update(status="pending", error=None)

        self.repo.mutate(work_id, request.expected_revision, change)
        self.service.worker.submit(self.run, work_id, job_id)
        return self.service.job(work_id, job_id)

    def run(self, work_id, job_id):
        def begin(value):
            job = next(j for j in value["jobs"] if j["id"] == job_id)
            if job["status"] != "pending":
                raise DomainError("JOB_NOT_PENDING", "任务已执行或中断", 409)
            job["status"] = "running"

        try:
            work = self.repo.mutate(work_id, None, begin)
        except DomainError:
            return
        try:
            job = next(j for j in work["jobs"] if j["id"] == job_id)
            for segment in job["segments"]:
                if segment["audio_id"]:
                    continue
                result = segment.get("result")
                if not result:

                    def sent(value):
                        entry = next(
                            e
                            for e in value["budget_entries"]
                            if e.get("segment_id") == segment["id"]
                        )
                        if entry["sent"]:
                            raise DomainError("TTS_UNCERTAIN", "此句已发送，禁止重新提交", 409)
                        entry["sent"] = True

                    self.repo.mutate(work_id, None, sent)
                    started = time.monotonic()
                    result = self.provider.synthesize(segment["text"])

                    def settled(value):
                        entry = next(
                            e
                            for e in value["budget_entries"]
                            if e.get("segment_id") == segment["id"]
                        )
                        cost = result["characters"] * MICRO_PER_CHAR
                        if cost > entry["reserved_micro"]:
                            entry.update(
                                status="uncertain", reserved_micro=cost, accounting_error=True
                            )
                            return
                        entry.update(
                            status="settled",
                            actual_micro=cost,
                            characters=result["characters"],
                            request_id=result["request_id"],
                            duration=round(time.monotonic() - started, 3),
                        )
                        target = next(j for j in value["jobs"] if j["id"] == job_id)
                        next(s for s in target["segments"] if s["id"] == segment["id"])[
                            "result"
                        ] = result

                    work = self.repo.mutate(work_id, None, settled)
                    if any(e.get("accounting_error") for e in work["budget_entries"]):
                        raise DomainError("USAGE_EXCEEDS_RESERVE", "配音计量超过预留，已暂停", 502)
                data = self.provider.download(result["url"])
                audio_id = uid()
                filename = audio_id + ".wav"
                with tempfile.TemporaryDirectory(prefix="knowledge-audio-") as temp:
                    source = Path(temp) / "source.wav"
                    source.write_bytes(data)
                    target = Path(temp) / "normalized.wav"
                    duration = normalize(source, target)
                    content = target.read_bytes()
                atomic_bytes(self.path(work_id, filename), content)
                asset = {
                    "id": audio_id,
                    "key": segment["key"],
                    "filename": filename,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "duration_ms": duration,
                    "model": job["model"],
                }

                def saved(value):
                    value.setdefault("audios", []).append(asset)
                    item = next(j for j in value["jobs"] if j["id"] == job_id)
                    next(s for s in item["segments"] if s["id"] == segment["id"])["audio_id"] = (
                        audio_id
                    )

                self.repo.mutate(work_id, None, saved)
            work = self.repo.get(work_id)
            job = next(j for j in work["jobs"] if j["id"] == job_id)
            export = job["export_snapshot"]
            assets = {a["id"]: a for a in work.get("audios", [])}
            pieces = []
            for segment in job["segments"]:
                audio = assets[segment["audio_id"]]
                if (
                    hashlib.sha256(self.path(work_id, audio["filename"]).read_bytes()).hexdigest()
                    != audio["sha256"]
                ):
                    raise DomainError("AUDIO_DAMAGED", "已保存音频校验失败，请恢复原文件", 503)
                index = next(
                    i for i, c in enumerate(export["cards"]) if c["id"] == segment["card_id"]
                )
                pieces.append(
                    {
                        **segment,
                        "audio_path": self.path(work_id, audio["filename"]),
                        "image_path": self.cards.path(work_id, export["files"][index]),
                        "duration_ms": audio["duration_ms"],
                        "scene_id": segment["scene_id"],
                        "scene_template": segment["scene_template"],
                        "scene_title": segment["scene_title"],
                        "scene_steps": segment["scene_steps"],
                        "scene_step_index": segment["scene_step_index"],
                    }
                )
            video_id = uid()
            filename = video_id + ".mp4"
            with tempfile.TemporaryDirectory(prefix="knowledge-video-") as temp:
                target = Path(temp) / "video.mp4"
                timeline, duration = render_video(Path(temp), pieces, target)
                content = target.read_bytes()
            atomic_bytes(self.path(work_id, filename), content)
            video = {
                "id": video_id,
                "fingerprint": job["fingerprint"],
                "filename": filename,
                "sha256": hashlib.sha256(content).hexdigest(),
                "export_id": export["id"],
                "duration_ms": duration,
                "timeline": timeline,
                "model": job["model"],
            }

            def complete(value):
                value.setdefault("videos", []).append(video)
                fresh = (
                    current(value)
                    and fingerprint(value) == job["fingerprint"]
                    and value.get("scenes_basis") == job.get("scenes_basis")
                    and digest(value.get("scenes", [])) == job.get("scenes_fingerprint")
                    and all(scene.get("confirmed") for scene in value.get("scenes", []))
                )
                next(j for j in value["jobs"] if j["id"] == job_id)["status"] = (
                    "completed" if fresh else "stale"
                )

            self.repo.mutate(work_id, None, complete)
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, DomainError)
                else DomainError("VIDEO_FAILED", "视频未完成，已保留音频、旧视频和费用", 502)
            )

            def fail(value):
                next(j for j in value["jobs"] if j["id"] == job_id).update(
                    status="failed", error={"code": error.code, "message": error.message}
                )
                for entry in value["budget_entries"]:
                    if (
                        entry["job_id"] == job_id
                        and entry["status"] != "settled"
                        and entry.get("sent")
                    ):
                        entry["status"] = "uncertain"

            self.repo.mutate(work_id, None, fail)

    def download(self, work_id, video_id):
        work = self.repo.get(work_id)
        video = next((v for v in work.get("videos", []) if v["id"] == video_id), None)
        if not video:
            raise DomainError("NOT_FOUND", "视频不存在", 404)
        path = self.path(work_id, video["filename"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != video["sha256"]:
            raise DomainError("ASSET_DAMAGED", "视频文件丢失或损坏，旧版记录仍保留", 503)
        return path
