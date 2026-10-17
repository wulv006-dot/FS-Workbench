# Exact member_state source; dependency q and current admin policy bound by caller.
def member_state(conn, username: str):
    """返回 (role, registered)。

    守护管理员恒定 admin 且视为已登记；未在 members 表出现的账号一律 (viewer, False)，
    由路由层按 CFG['unregistered'] 决定拒绝还是只读放行。
    """
    if not username:
        return "anonymous", False
    if username in GUARD_ADMINS:
        return "admin", True
    row = q(conn, "SELECT role,active FROM members WHERE username=?", (username,), one=True)
    if not row:
        return "viewer", False
    if not row["active"]:
        return "viewer", True          # 已登记但被停用：降级只读，不再具备写权限
    return (row["role"] if row["role"] in ROLES else "viewer"), True
