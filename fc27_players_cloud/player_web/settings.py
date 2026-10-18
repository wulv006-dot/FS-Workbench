from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    data_root: Path
    player_db_base_url: str
    admin_api_base_url: str
    public_origin: str
    root_path: str
    write_enabled: bool
    collector_enabled: bool
    lookback_days: int
    max_candidates: int
    source_timeout: float
    approved_public_http_source: str = ""
    manual_new_cards_enabled: bool = False
    manual_model_images_enabled: bool = False
    manual_existing_recommend_enabled: bool = False
    shared_backend_session: bool = False

    def existing_action_write_enabled(self, action: str) -> bool:
        return self.write_enabled or (self.manual_existing_recommend_enabled and action == "recommend_enable")

    @property
    def model_image_write_enabled(self) -> bool:
        return self.write_enabled or self.manual_model_images_enabled

    @property
    def http_source_approved(self) -> bool:
        # Explicit, deployment-side approval is limited to this public database.
        return (self.approved_public_http_source == "http://139.28.18.234:8001"
                and self.player_db_base_url == self.approved_public_http_source)

    @property
    def new_card_write_enabled(self) -> bool:
        return self.write_enabled or self.manual_new_cards_enabled

    @property
    def source_transport(self) -> str:
        if self.player_db_base_url.startswith("http://"):
            return "http_explicitly_approved" if self.http_source_approved else "http_unverified"
        return "https"

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(os.environ.get("DATA_ROOT", "./data")).resolve()
        source = os.environ.get("PLAYER_DB_BASE_URL", "").strip().rstrip("/")
        admin = os.environ.get("ADMIN_API_BASE_URL", "https://admin-api.p2pah.cn").strip().rstrip("/")
        origin = os.environ.get("PUBLIC_ORIGIN", "").strip().rstrip("/")
        prefix = os.environ.get("APP_ROOT_PATH", "/tools/fc27-players").strip().rstrip("/")
        if source:
            parsed = urlsplit(source)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("PLAYER_DB_BASE_URL 必须是已核实的服务根地址")
        if admin != "https://admin-api.p2pah.cn":
            raise ValueError("后台基址不在 FC27 Players 白名单")
        if origin:
            parsed_origin = urlsplit(origin)
            if parsed_origin.scheme != "https" or not parsed_origin.hostname or parsed_origin.path not in {"", "/"}:
                raise ValueError("PUBLIC_ORIGIN 必须是 HTTPS 源")
        if not prefix.startswith("/") or prefix == "/" or "//" in prefix:
            raise ValueError("APP_ROOT_PATH 无效")
        days = int(os.environ.get("LOOKBACK_DAYS", "3"))
        maximum = int(os.environ.get("MAX_CANDIDATES", "50000"))
        approved_http = os.environ.get("APPROVED_PUBLIC_HTTP_SOURCE", "").strip().rstrip("/")
        if approved_http and (approved_http != "http://139.28.18.234:8001" or source != approved_http):
            raise ValueError("公开 HTTP 来源批准仅适用于指定球员数据库")
        if not 1 <= days <= 90 or not 1 <= maximum <= 100000:
            raise ValueError("拉取窗口或候选上限无效")
        return cls(
            data_root=root,
            player_db_base_url=source,
            admin_api_base_url=admin,
            public_origin=origin,
            root_path=prefix,
            write_enabled=os.environ.get("WRITE_ENABLED", "false").lower() == "true",
            collector_enabled=os.environ.get("COLLECTOR_ENABLED", "false").lower() == "true",
            lookback_days=days,
            max_candidates=maximum,
            source_timeout=float(os.environ.get("SOURCE_TIMEOUT_SECONDS", "30")),
            approved_public_http_source=approved_http,
            manual_new_cards_enabled=os.environ.get("MANUAL_NEW_CARDS_ENABLED", "false").lower() == "true",
            manual_model_images_enabled=os.environ.get("MANUAL_MODEL_IMAGES_ENABLED", "false").lower() == "true",
            manual_existing_recommend_enabled=os.environ.get("MANUAL_EXISTING_RECOMMEND_ENABLED", "false").lower() == "true",
            shared_backend_session=os.environ.get("FS_SHARED_BACKEND_SESSION", "false").lower() == "true",
        )
