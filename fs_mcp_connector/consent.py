"""Server-rendered authorization screens using the existing FS UI assets."""
from html import escape


def _shell(title, content, asset_base):
    if not asset_base.startswith('/') or asset_base.startswith('//') or any(c in asset_base for c in '\\?#\r\n'):
        raise ValueError('same_origin_asset_path_required')
    assets = escape(asset_base.rstrip('/'), quote=True)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="确认客户端按你现有的 FS 权限读取数据。">
<title>{escape(title)} | FS</title>
<link rel="stylesheet" href="{assets}/fs-tokens.css">
<link rel="stylesheet" href="{assets}/fs-ui.css">
<link rel="stylesheet" href="{assets}/consent.css">
<script src="{assets}/fs-theme.js" defer></script></head>
<body class="fs-ui-page connector-page"><main class="connector-consent" aria-labelledby="page-title">
<header class="connector-brand">FS 数据连接</header>{content}
</main></body></html>'''


def render_consent(*, principal, client_name, redirect_uri, pending_id, csrf_token, oauth_base, asset_base):
    if not oauth_base.startswith('/') or oauth_base.startswith('//') or any(c in oauth_base for c in '\\?#\r\n'):
        raise ValueError('same_origin_form_path_required')
    esc = lambda value: escape(str(value), quote=True)
    content = f'''
<h1 id="page-title">连接 FS 数据</h1>
<p class="connector-lead">确认后，客户端可按你的现有权限读取 FS 数据。</p>
<dl class="connector-identity"><div><dt>当前账号</dt><dd>{esc(principal.subject)}</dd></div>
<div><dt>请求连接的客户端</dt><dd>{esc(client_name)}</dd></div></dl>
<section class="connector-scope" aria-labelledby="scope-title"><h2 id="scope-title">本次仅授权读取</h2>
<p>可读取你有权查看的数据，包括原有 private 权限内的客户、订单和个人资料。连接不会扩大你的权限，也不提供改价、发券或其他业务写入。</p></section>
<details class="connector-callback"><summary>查看客户端回调地址</summary>
<p class="connector-address">{esc(redirect_uri)}</p></details>
<form method="post" action="{esc(oauth_base.rstrip('/'))}/authorize" class="connector-actions">
<input type="hidden" name="pending_id" value="{esc(pending_id)}">
<input type="hidden" name="csrf_token" value="{esc(csrf_token)}">
<button class="fs-btn fs-btn--primary" type="submit" name="decision" value="approve">允许读取</button>
<button class="fs-btn" type="submit" name="decision" value="deny">取消</button>
</form>'''
    return _shell('连接 FS 数据', content, asset_base)


def render_browser_error(*, reason='invalid_request', asset_base):
    message = {
        'login_required': '登录已失效。请重新登录 FS，再回到客户端重新连接。',
        'access_denied': '当前账号无法完成此次授权。请确认 FS 权限后，回到客户端重新连接。',
        'temporarily_unavailable': '暂时无法确认 FS 授权状态。请稍后回到客户端重新连接。',
    }.get(reason, '此次连接请求已失效或无法验证。请回到客户端重新发起连接。')
    content = f'''<h1 id="page-title">暂未完成连接</h1>
<p class="connector-lead" role="alert">{message}</p>
<p class="connector-help">你可以返回 FS 检查登录状态。</p>
<div class="connector-actions"><a class="fs-btn" href="/dashboard/">返回 FS</a></div>'''
    return _shell('暂未完成连接', content, asset_base)
