from __future__ import annotations

from fastapi import APIRouter

from backend.schemas import SettingsUpdate
from backend.services.settings_service import SettingsService

router = APIRouter()
service = SettingsService()


def _payload_dict(payload: SettingsUpdate) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_none=True)
    return payload.dict(exclude_none=True)


@router.get("")
def get_settings():
    return service.get_all()


@router.put("")
def update_settings(payload: SettingsUpdate):
    service.update_many(_payload_dict(payload))
    return service.get_all()


@router.patch("")
def patch_settings(payload: SettingsUpdate):
    service.update_many(_payload_dict(payload))
    return service.get_all()
