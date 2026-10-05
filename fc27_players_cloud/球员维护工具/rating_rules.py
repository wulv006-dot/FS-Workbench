"""评分规则的无界面入口；逻辑仍以已有 app_formatters 实现为唯一来源。"""
from .app_formatters import is_low_rating_player, new_card_rating_threshold, parse_player_rating

__all__ = ["is_low_rating_player", "new_card_rating_threshold", "parse_player_rating"]
