"""Add only the merged email lifecycle block to the verified live workspace."""
import hashlib

EXPECTED_SHA256 = '4f4a56f7a335357f0a83ab0034a49b8757a6cd6eef64541dfba837249c38fba0'
ANCHOR = b'  return {dispose() { for (const panel of panels) panel.invalidate(); section.remove(); }};'
REPLACEMENT = '''  let disposed = false, emailWidget, emailHost;
  if (options.orderEmailExport) {
    emailHost = el('div');
    const status = el('p', '订单用户邮箱导出正在加载…', 'hint');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    section.append(status, emailHost);
    const {endpoint, sites, games, fetch, paged} = options.orderEmailExport;
    import('./order-email-panel.js').then(({mountOrderEmailExcelExport}) => {
      if (disposed) return;
      emailWidget = mountOrderEmailExcelExport(emailHost, {endpoint, sites, games, fetch, paged});
      status.textContent = '邮箱 Excel 导出已就绪；尚未查询';
    }).catch(() => {
      if (disposed) return;
      emailHost.replaceChildren();
      status.textContent = '邮箱导出暂不可用，请稍后重试';
    });
  }
  return {dispose() {
    if (disposed) return;
    disposed = true;
    emailWidget?.dispose(); emailWidget = null;
    emailHost?.replaceChildren();
    for (const panel of panels) panel.invalidate();
    section.remove();
  }};'''.encode('utf8')


def prepare_workspace(source):
    if hashlib.sha256(source).hexdigest() != EXPECTED_SHA256:
        raise ValueError('workspace_baseline_changed')
    if source.count(ANCHOR) != 1:
        raise ValueError('workspace_anchor_changed')
    return source.replace(ANCHOR, REPLACEMENT, 1)
