"""Offline speech contracts and actual local MP4 encoding; no cloud calls."""

import io
import json
import math
import struct
import wave
from pathlib import Path

import httpx
import pytest
from test_cards import deck, edit_request, run_job  # noqa: F401

from scenarios.knowledge_diagram.repository import DomainError, Repository
from scenarios.knowledge_diagram.scenes import SceneEdit, Scenes
from scenarios.knowledge_diagram.schemas import Versioned
from scenarios.knowledge_diagram.service import budget, public_work
from scenarios.knowledge_diagram.tts_provider import TTSProvider
from scenarios.knowledge_diagram.video_schema import VideoRequest
from scenarios.knowledge_diagram.videos import Videos, split_text


class FakeTTS:
    key, enabled, pricing_confirmed, model, voice = (
        "fake-test",
        True,
        True,
        "offline-tts-test",
        "Cherry",
    )

    def __init__(self):
        self.calls = 0

    def ready(self):
        pass

    def synthesize(self, text):
        self.calls += 1
        return {"url": "offline", "characters": len(text), "request_id": "offline-tts"}

    def download(self, url):
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            # A test tone, explicitly not a human or synthesized narration.
            audio.writeframes(
                b"".join(
                    struct.pack("<h", int(1000 * math.sin(i * 2 * math.pi * 220 / 24000)))
                    for i in range(24000 * 3)
                )
            )
        return output.getvalue()


@pytest.fixture
def video_system(request):
    return prepare_video(request.getfixturevalue("deck"))


def prepare_video(pair):
    cards, work = pair
    for i, card in enumerate(work["cards"]):
        narration = f"这是第{i + 1}张卡片的离线测试旁白，配音请求只使用测试替身。字幕按照每一句音频的真实时长切换，测试结果不代表真实音色效果。"
        work = cards.edit(
            work["id"], card["id"], edit_request_for(card, work["revision"], narration)
        )
        work, _ = run_job(cards, work, "illustration", card["id"], f"video-image-{i}")
    work, _ = run_job(cards, work, operation="video-pngs")
    scenes = Scenes(cards.repo)
    work = scenes.draft(work["id"], Versioned(expected_revision=work["revision"]))
    for scene in list(work["scenes"]):
        request = SceneEdit(
            expected_revision=work["revision"], title=scene["title"], template="flow",
            narration=scene["narration"], steps=[
                {"label": "定位原文", "detail": "定位对应的引用内容。"},
                {"label": "核对观点", "detail": "对照原文确认观点含义。"},
            ],
        )
        work = scenes.edit(work["id"], scene["id"], request)
        work = scenes.confirm(work["id"], scene["id"], Versioned(expected_revision=work["revision"]))
    videos = Videos(cards.service, cards, FakeTTS())
    return videos, work


def edit_request_for(card, revision, narration):
    from scenarios.knowledge_diagram.cards_schema import CardEdit

    values = {k: card[k] for k in ("title", "body", "narration", "prompt", "template")}
    return CardEdit(**{**values, "narration": narration}, expected_revision=revision)


def confirm_scenes(videos, work):
    scenes = Scenes(videos.repo)
    work = scenes.draft(work["id"], Versioned(expected_revision=work["revision"]))
    for scene in list(work["scenes"]):
        request = SceneEdit(
            expected_revision=work["revision"], title=scene["title"], template="flow",
            narration=scene["narration"], steps=[
                {"label": "定位原文", "detail": "定位对应的引用内容。"},
                {"label": "核对观点", "detail": "对照原文确认观点含义。"},
            ],
        )
        work = scenes.edit(work["id"], scene["id"], request)
        work = scenes.confirm(work["id"], scene["id"], Versioned(expected_revision=work["revision"]))
    return work


def start(videos, work):
    job = videos.start(
        work["id"],
        VideoRequest(
            expected_revision=work["revision"],
            operation_id="video-offline-01",
            max_cost_micro=60_000,
        ),
        submit=False,
    )
    return job


def test_split_preserves_text_and_caption_width():
    text = "原文提炼与补充说明应分别标注，不能混淆。" + ("长句" * 30) + "！"
    parts = split_text(text)
    assert "".join(parts) == text and all(len(s) <= 24 for s in parts)


def test_missing_or_unconfirmed_storyboard_blocks_video(video_system):
    videos, work = video_system
    work["scenes"][0]["confirmed"] = False
    videos.repo.mutate(work["id"], work["revision"], lambda value: value.update(scenes=work["scenes"]))
    with pytest.raises(DomainError, match="STORYBOARD_REQUIRED"):
        videos.public_plan(videos.repo.get(work["id"]))
    assert videos.provider.calls == 0


def test_short_narration_blocks_network(video_system):
    videos, work = video_system
    card = work["cards"][0]
    work = videos.cards.edit(
        work["id"], card["id"], edit_request_for(card, work["revision"], "短句。")
    )
    with pytest.raises(DomainError, match="IMAGES_REQUIRED"):
        start(videos, work)
    assert videos.provider.calls == 0


def test_unknown_sentence_stops_all_subsequent_sends_and_reserve_persists(
    video_system, monkeypatch
):
    videos, work = video_system
    monkeypatch.setattr(
        videos.provider,
        "synthesize",
        lambda text: (_ for _ in ()).throw(DomainError("TTS_UNCERTAIN", "测试结果未知")),
    )
    job = start(videos, work)
    videos.run(work["id"], job["id"])
    work = videos.repo.get(work["id"])
    entries = [e for e in work["budget_entries"] if e["job_id"] == job["id"]]
    assert sum(e["sent"] for e in entries) == 1
    assert sum(e["status"] == "uncertain" for e in entries) == 1
    assert budget(work)["reserved_micro"] > 0
    Repository(videos.repo.root).recover()
    with pytest.raises(DomainError, match="ACCOUNTING_UNCERTAIN"):
        videos.resume(work["id"], job["id"], Versioned(expected_revision=work["revision"]))


def test_crash_before_send_can_resume_without_uncertain_charge(video_system):
    videos, work = video_system
    job = start(videos, work)
    Repository(videos.repo.root).recover()
    work = videos.repo.get(work["id"])
    assert work["jobs"][-1]["status"] == "interrupted"
    assert all(
        e["status"] == "reserved" for e in work["budget_entries"] if e["job_id"] == job["id"]
    )
    assert videos.provider.calls == 0


def test_paid_plan_and_idempotency(video_system):
    videos, work = video_system
    plan = videos.public_plan(work)
    assert 180 <= plan["characters"] <= 240 and 0 < plan["reserve_micro"] <= 60_000
    job = start(videos, work)
    duplicate = start(videos, work)
    assert duplicate["id"] == job["id"] and videos.provider.calls == 0


def test_actual_mp4_timeline_old_version_and_audio_reuse(video_system, monkeypatch, tmp_path):
    import imageio_ffmpeg

    videos, work = video_system
    job = start(videos, work)
    videos.run(work["id"], job["id"])
    work = videos.repo.get(work["id"])
    assert work["jobs"][-1]["status"] == "completed", work["jobs"][-1]["error"]
    video = work["videos"][0]
    path = videos.download(work["id"], video["id"])
    reader = imageio_ffmpeg.read_frames(str(path))
    meta = next(reader)
    reader.close()
    assert meta["size"] == (1080, 1920) and meta["fps"] == 25
    assert 30 <= meta["duration"] <= 60
    assert abs(meta["duration"] * 1000 - video["duration_ms"]) < 100
    assert video["timeline"][0]["start_ms"] == 0
    assert all("scene_id" in cue and "scene_step_index" in cue for cue in video["timeline"])
    assert all(
        a["end_ms"] == b["start_ms"] for a, b in zip(video["timeline"], video["timeline"][1:])
    )
    assert video["timeline"][-1]["end_ms"] == video["duration_ms"]
    calls = videos.provider.calls
    card = work["cards"][0]
    edit = edit_request_for(card, work["revision"], card["narration"])
    edit.title = "已改标题"
    work = videos.cards.edit(work["id"], card["id"], edit)
    assert work["videos"][0]["fingerprint"] != public_work(work)["deck_fingerprint"]
    assert videos.download(work["id"], video["id"]).read_bytes() == path.read_bytes()
    work, _ = run_job(videos.cards, work, operation="video-updated-png")
    work = confirm_scenes(videos, work)
    assert videos.public_plan(work)["reserve_micro"] == 0
    assert videos.provider.calls == calls
    # Keep a standalone offline artifact for manual inspection, never label it real speech.
    out = Path(__file__).resolve().parents[2] / "docs/验收材料/阶段2-3离线视频"
    out.mkdir(parents=True, exist_ok=True)
    (out / "离线测试音-字幕视频.mp4").write_bytes(path.read_bytes())


def test_download_failure_resumes_from_original_url_without_new_paid_send(
    video_system, monkeypatch
):
    videos, work = video_system
    original = videos.provider.download
    monkeypatch.setattr(
        videos.provider,
        "download",
        lambda url: (_ for _ in ()).throw(DomainError("AUDIO_DOWNLOAD_FAILED", "下载失败")),
    )
    job = start(videos, work)
    videos.run(work["id"], job["id"])
    work = videos.repo.get(work["id"])
    assert videos.provider.calls == 1 and work["jobs"][-1]["status"] == "failed"
    assert (
        next(e for e in work["budget_entries"] if e["job_id"] == job["id"])["status"] == "settled"
    )
    assert (
        next(j for j in work["jobs"] if j["id"] == job["id"])["segments"][0]["result"]["url"]
        == "offline"
    )
    monkeypatch.setattr(videos.provider, "download", original)
    import scenarios.knowledge_diagram.videos as module

    def local_render(directory, pieces, target):
        target.write_bytes(b"offline-render-test")
        return [], 36000

    monkeypatch.setattr(module, "render_video", local_render)
    expected = len(next(j for j in work["jobs"] if j["id"] == job["id"])["segments"])
    videos.resume(work["id"], job["id"], Versioned(expected_revision=work["revision"]))
    videos.service.worker.shutdown(wait=True)
    restored = videos.repo.get(work["id"])
    assert restored["jobs"][-1]["status"] == "completed"
    assert (
        videos.provider.calls == expected
    )  # first successful TTS was downloaded again, never resent


def test_tts_http_contract_usage_and_single_send(monkeypatch):
    for k, v in {
        "DASHSCOPE_API_KEY": "fake-test",
        "KNOWLEDGE_ALLOW_TTS": "1",
        "KNOWLEDGE_TTS_PRICING_CONFIRMED": "1",
    }.items():
        monkeypatch.setenv(k, v)
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["model"] == "qwen3-tts-flash" and body["input"]["voice"] == "Cherry"
        return httpx.Response(
            200,
            json={
                "output": {
                    "finish_reason": "stop",
                    "audio": {"url": "https://bucket.oss-cn-beijing.aliyuncs.com/a.wav"},
                },
                "usage": {"characters": 4},
                "request_id": "offline",
            },
        )

    real = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)
    )
    provider = TTSProvider()
    assert provider.synthesize("测试配音")["characters"] == 4 and len(calls) == 1
    with pytest.raises(DomainError, match="AUDIO_URL_REJECTED"):
        provider.download("https://localhost/private.wav")
