from __future__ import annotations

from 球员维护工具.admin_client import AdminClient
from 球员维护工具.player_database import PlayerDatabaseClient

from .settings import Settings


def player_client(settings: Settings) -> PlayerDatabaseClient:
    if not settings.player_db_base_url:
        raise RuntimeError("球员数据库地址尚未核实，采集已阻断")
    return PlayerDatabaseClient(settings.player_db_base_url, timeout=settings.source_timeout)


def admin_client(settings: Settings) -> AdminClient:
    return AdminClient(settings.admin_api_base_url)
