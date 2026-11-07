from fastapi import APIRouter

from core.stages import stage_catalog

router = APIRouter(tags=["Stages"])


@router.get("/api/stages")
async def list_stages():
    return {"stages": stage_catalog()}
