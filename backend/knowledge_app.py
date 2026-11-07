"""Local-only product entrypoint. The upstream unrestricted API is NOT mounted."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from scenarios.knowledge_diagram.cards import Cards
from scenarios.knowledge_diagram.cards_schema import CardEdit, CardOrder, ImageRequest
from scenarios.knowledge_diagram.provider import Provider
from scenarios.knowledge_diagram.repository import DomainError, Repository
from scenarios.knowledge_diagram.scenes import SceneEdit, Scenes
from scenarios.knowledge_diagram.schemas import (
    ClaimEdit,
    ClaimSelection,
    ExtractRequest,
    HealthResponse,
    JobResponse,
    Material,
    MergeClaims,
    SaveMaterial,
    Versioned,
    WorkResponse,
    WorksResponse,
)
from scenarios.knowledge_diagram.service import Service, public_work
from scenarios.knowledge_diagram.video_schema import VideoPlan, VideoRequest
from scenarios.knowledge_diagram.videos import Videos


def create_app(directory=None, provider=None, image_provider=None, tts_provider=None):
    repo = Repository(
        directory
        or os.getenv("KNOWLEDGE_DATA_DIR")
        or Path(__file__).resolve().parents[1] / "data/knowledge"
    )
    service = Service(repo, provider or Provider())
    cards = Cards(service, image_provider)
    videos = Videos(service, cards, tts_provider)

    @asynccontextmanager
    async def lifespan(app):
        repo.recover()
        yield
        service.worker.shutdown(wait=True)

    app = FastAPI(title="知识图解工作台", lifespan=lifespan)
    app.state.service = service
    app.state.cards = cards
    app.state.videos = videos

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.url.hostname
        origin = request.headers.get("origin")
        if host not in {"127.0.0.1", "localhost"} or (
            origin and origin not in {"http://127.0.0.1:3137", "http://localhost:3137"}
        ):
            return JSONResponse(
                {"error": {"code": "LOCAL_ONLY", "message": "此工作台仅允许本机访问"}},
                status_code=403,
            )
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 100_000):
            return JSONResponse(
                {"error": {"code": "REQUEST_TOO_LARGE", "message": "请求内容过大"}}, status_code=413
            )
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {"error": {"code": "VALIDATION_ERROR", "message": "请检查正文长度、来源链接及必填项"}},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def safe_error(request, exc):
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "操作未完成，已保存的数据不会被覆盖"}},
            status_code=500,
        )

    prefix = "/api/knowledge"

    @app.get(prefix + "/health", response_model=HealthResponse)
    def health():
        return {
            "status": "ok",
            "model_configured": bool(service.provider.key),
            "paid_calls_enabled": service.provider.enabled,
            "pricing_confirmed": service.provider.pricing_confirmed,
            "model": service.provider.model,
            "image_configured": bool(cards.provider.key),
            "image_enabled": cards.provider.enabled and cards.provider.pricing_confirmed,
            "image_price_micro": 40_000,
            "tts_configured": bool(videos.provider.key),
            "tts_enabled": videos.provider.enabled and videos.provider.pricing_confirmed,
            "tts_model": videos.provider.model,
        }

    @app.get(prefix + "/works", response_model=WorksResponse)
    def list_works():
        return {"works": [public_work(w) for w in repo.list()]}

    @app.post(prefix + "/works", response_model=WorkResponse, status_code=201)
    def create(request: Material):
        return {"work": public_work(repo.create(request.model_dump()))}

    @app.get(prefix + "/works/{work_id}", response_model=WorkResponse)
    def get(work_id: str):
        return {"work": public_work(repo.get(work_id))}

    @app.put(prefix + "/works/{work_id}/material", response_model=WorkResponse)
    def save(work_id: str, request: SaveMaterial):
        return {"work": public_work(service.save_material(work_id, request))}

    @app.post(prefix + "/works/{work_id}/extract", response_model=JobResponse, status_code=202)
    def extract(work_id: str, request: ExtractRequest):
        return {"job": service.start_extraction(work_id, request)}

    @app.get(prefix + "/works/{work_id}/jobs/{job_id}", response_model=JobResponse)
    def get_job(work_id: str, job_id: str):
        return {"job": service.job(work_id, job_id)}

    @app.patch(prefix + "/works/{work_id}/claims/{claim_id}", response_model=WorkResponse)
    def edit(work_id: str, claim_id: str, request: ClaimEdit):
        return {"work": public_work(service.edit(work_id, claim_id, request))}

    @app.post(prefix + "/works/{work_id}/confirm", response_model=WorkResponse)
    def confirm(work_id: str, request: ClaimSelection):
        return {"work": public_work(service.confirm(work_id, request))}

    @app.post(prefix + "/works/{work_id}/claims/{claim_id}/remove", response_model=WorkResponse)
    def remove(work_id: str, claim_id: str, request: Versioned):
        return {"work": public_work(service.remove(work_id, claim_id, request))}

    @app.post(prefix + "/works/{work_id}/merge", response_model=WorkResponse)
    def merge(work_id: str, request: MergeClaims):
        return {"work": public_work(service.merge(work_id, request))}

    @app.post(prefix + "/works/{work_id}/cards/draft", response_model=WorkResponse)
    def draft_cards(work_id: str, request: Versioned):
        return {"work": public_work(cards.draft(work_id, request))}

    @app.patch(prefix + "/works/{work_id}/cards/{card_id}", response_model=WorkResponse)
    def edit_card(work_id: str, card_id: str, request: CardEdit):
        return {"work": public_work(cards.edit(work_id, card_id, request))}

    @app.post(prefix + "/works/{work_id}/cards/order", response_model=WorkResponse)
    def order_cards(work_id: str, request: CardOrder):
        return {"work": public_work(cards.order(work_id, request))}

    @app.post(
        prefix + "/works/{work_id}/cards/{card_id}/illustration",
        response_model=JobResponse,
        status_code=202,
    )
    def generate_image(work_id: str, card_id: str, request: ImageRequest):
        return {"job": cards.start(work_id, request, "illustration", card_id)}

    @app.post(prefix + "/works/{work_id}/exports", response_model=JobResponse, status_code=202)
    def export_cards(work_id: str, request: ExtractRequest):
        return {"job": cards.start(work_id, request, "export")}

    @app.post(
        prefix + "/works/{work_id}/jobs/{job_id}/resume",
        response_model=JobResponse,
        status_code=202,
    )
    def resume_image(work_id: str, job_id: str, request: Versioned):
        return {"job": cards.resume(work_id, job_id, request)}

    @app.get(prefix + "/works/{work_id}/exports/{version_id}/{number}")
    def download_cards(work_id: str, version_id: str, number: str):
        path, name = cards.download(work_id, version_id, number)
        return FileResponse(
            path,
            filename=name,
            media_type="application/zip" if number == "all.zip" else "image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.get(prefix + "/works/{work_id}/illustrations/{image_id}")
    def illustration(work_id: str, image_id: str):
        work = repo.get(work_id)
        image = next((i for i in work.get("illustrations", []) if i["id"] == image_id), None)
        if not image:
            raise DomainError("NOT_FOUND", "插图不存在", 404)
        path = cards.path(work_id, image["filename"])
        if not path.is_file():
            raise DomainError("ASSET_MISSING", "插图文件丢失，请恢复原文件", 404)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get(prefix + "/works/{work_id}/video-plan", response_model=VideoPlan)
    def video_plan(work_id: str):
        return videos.public_plan(repo.get(work_id))

    @app.post(prefix + "/works/{work_id}/videos", response_model=JobResponse, status_code=202)
    def generate_video(work_id: str, request: VideoRequest):
        return {"job": videos.start(work_id, request)}

    @app.post(
        prefix + "/works/{work_id}/video-jobs/{job_id}/resume",
        response_model=JobResponse,
        status_code=202,
    )
    def resume_video(work_id: str, job_id: str, request: Versioned):
        return {"job": videos.resume(work_id, job_id, request)}

    @app.get(prefix + "/works/{work_id}/videos/{video_id}.mp4")
    def download_video(work_id: str, video_id: str):
        return FileResponse(
            videos.download(work_id, video_id),
            filename="知识图解.mp4",
            media_type="video/mp4",
            headers={"Cache-Control": "no-store"},
        )

    scenes = Scenes(repo)

    @app.post(prefix + "/works/{work_id}/scenes/draft", response_model=WorkResponse)
    def draft_scenes(work_id: str, request: Versioned):
        return {"work": public_work(scenes.draft(work_id, request))}

    @app.patch(prefix + "/works/{work_id}/scenes/{scene_id}", response_model=WorkResponse)
    def edit_scene(work_id: str, scene_id: str, request: SceneEdit):
        return {"work": public_work(scenes.edit(work_id, scene_id, request))}

    @app.post(prefix + "/works/{work_id}/scenes/{scene_id}/confirm", response_model=WorkResponse)
    def confirm_scene(work_id: str, scene_id: str, request: Versioned):
        return {"work": public_work(scenes.confirm(work_id, scene_id, request))}

    return app


load_dotenv(Path(__file__).with_name(".env"), override=False)
app = create_app()
