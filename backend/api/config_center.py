"""
配置中心API

提供统一的配置管理接口，确保前端和Agent使用相同的配置。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import (
    AgentConfig,
    AgentConfigOut,
    BacktestPreset,
    BacktestPresetOut,
    SystemInfo,
)
from backend.services.config_center_service import ConfigCenterService

router = APIRouter()
service = ConfigCenterService()


# ==================== 回测预设管理 ====================

@router.get("/presets", response_model=list[BacktestPresetOut], tags=["config-presets"])
def list_presets():
    """获取所有回测预设配置"""
    return service.list_presets()


@router.get("/presets/default", response_model=BacktestPresetOut | None, tags=["config-presets"])
def get_default_preset():
    """获取默认回测预设"""
    return service.get_default_preset()


@router.get("/presets/{preset_id}", response_model=BacktestPresetOut, tags=["config-presets"])
def get_preset(preset_id: int):
    """获取指定回测预设"""
    preset = service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")
    return preset


@router.post("/presets", response_model=BacktestPresetOut, tags=["config-presets"])
def create_preset(payload: BacktestPreset):
    """创建回测预设配置"""
    return service.create_preset(payload)


@router.put("/presets/{preset_id}", response_model=BacktestPresetOut, tags=["config-presets"])
def update_preset(preset_id: int, payload: BacktestPreset):
    """更新回测预设配置"""
    preset = service.update_preset(preset_id, payload)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")
    return preset


@router.delete("/presets/{preset_id}", tags=["config-presets"])
def delete_preset(preset_id: int):
    """删除回测预设"""
    if not service.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="预设不存在")
    return {"ok": True, "message": "预设已删除"}


# ==================== Agent配置管理 ====================

@router.get("/agents", response_model=list[AgentConfigOut], tags=["config-agents"])
def list_agents():
    """获取所有Agent配置"""
    return service.list_agents()


@router.get("/agents/{agent_id}", response_model=AgentConfigOut, tags=["config-agents"])
def get_agent(agent_id: int):
    """获取指定Agent配置"""
    agent = service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent配置不存在")
    return agent


@router.post("/agents", response_model=AgentConfigOut, tags=["config-agents"])
def create_agent(payload: AgentConfig):
    """创建Agent配置"""
    return service.create_agent(payload)


@router.put("/agents/{agent_id}", response_model=AgentConfigOut, tags=["config-agents"])
def update_agent(agent_id: int, payload: AgentConfig):
    """更新Agent配置"""
    agent = service.update_agent(agent_id, payload)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent配置不存在")
    return agent


@router.delete("/agents/{agent_id}", tags=["config-agents"])
def delete_agent(agent_id: int):
    """删除Agent配置"""
    if not service.delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent配置不存在")
    return {"ok": True, "message": "Agent配置已删除"}


# ==================== 系统信息 ====================

@router.get("/system-info", response_model=SystemInfo, tags=["config-system"])
def get_system_info():
    """获取系统信息"""
    return service.get_system_info()
