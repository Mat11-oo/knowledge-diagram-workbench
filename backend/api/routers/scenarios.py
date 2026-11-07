from fastapi import APIRouter, HTTPException

from api.dependencies import workflow_engine
from config import settings

router = APIRouter(tags=["Scenarios"])


@router.get("/api/scenarios")
async def list_scenarios():
    registry = workflow_engine.scenarios
    return {
        "default": registry.default_id(settings.DEFAULT_SCENARIO),
        "scenarios": [scenario.to_dict() for scenario in registry.list()],
        # 声明有误、被跳过的场景包：{目录名: 错误原因}
        "errors": dict(registry.errors),
    }


@router.get("/api/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str):
    scenario = workflow_engine.scenarios.get(scenario_id)
    if scenario is None:
        raise HTTPException(404, f"Scenario not found: {scenario_id}")
    return scenario.to_dict()


@router.post("/api/scenarios/reload")
async def reload_scenarios():
    """Re-read backend/scenarios/ after editing a scenario.yaml, without restarting the server."""
    workflow_engine.scenarios.reload()
    return await list_scenarios()
