"""FC27 本地球员维护工具。

GUI、运行编排与只读球员数据库客户端保持分层；数据库客户端只访问已核实
的查询、导出和状态端点，不承担导入、采集或后台设置。
"""

__version__ = "0.1.0"

from .player_database import PlayerDatabaseClient, PlayerQueryResult, WorkbookValidation, validate_xlsx

__all__ = ["PlayerDatabaseClient", "PlayerQueryResult", "WorkbookValidation", "validate_xlsx"]
