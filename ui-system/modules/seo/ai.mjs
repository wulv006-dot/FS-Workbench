export async function mount(root, client) {
  const message = document.createElement('p'); message.setAttribute('role', 'status'); root.append(message); message.textContent = '正在读取AI设置…';
  try {
    let policy = await client.get('ai-policy');
    const controls = document.createElement('fieldset'); controls.className = 'ai-controls';
    const legend = document.createElement('legend'); legend.textContent = 'SEO AI增强'; controls.append(legend);
    const entries = [['总开关', null], ...Object.keys(policy.projects).map(game => [game, game])];
    const update = () => {controls.querySelectorAll('input').forEach(input => {input.checked = input.dataset.game ? policy.projects[input.dataset.game].ai_enabled : policy.ai_enabled; input.disabled = !policy.can_manage;});};
    for (const [label, game] of entries) {
      const row = document.createElement('label'), input = document.createElement('input'); input.type = 'checkbox'; if (game) input.dataset.game = game;
      row.append(input, document.createTextNode(label)); controls.append(row);
      input.addEventListener('change', async () => {
        const patch = game ? {projects: {[game]: input.checked}} : {ai_enabled: input.checked}; controls.disabled = true; message.textContent = '正在保存…';
        try {policy = await client.get('ai-policy', {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'FS-SEO'}, body: JSON.stringify({expected_revision: policy.revision, patch})}); policy.can_manage = true; message.textContent = '设置已保存；AI服务接通后在夜间生成分析。';}
        catch (error) {message.textContent = error.message;}
        finally {controls.disabled = false; update();}
      });
    }
    root.prepend(controls); update(); message.textContent = policy.runtime_status === 'not_configured' ? 'AI服务尚未接入，开关可独立保存；基础数据正常运行。' : policy.ai_enabled ? '等待下次夜间分析；数据快照保持不变。' : 'AI已关闭；数据采集、规则提醒和历史查询照常运行。';
  } catch {message.textContent = 'AI 设置暂不可用';}
}
