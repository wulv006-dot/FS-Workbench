"""Reviewed static navigation release only. Default inspection never writes.

Linux apply/rollback use exact target allowlist, manifest approval SHA, shared
gateway lock, per-file CAS, durable backups and rollback of this release only.
Permission scope changes exactly eight auth/taskboard assets and restarts those
two services. SQLite backups remain server-private; rollback never restores data.
Legacy rollback is refused after the first module-permission save.
"""
import argparse, contextlib, hashlib, json, os, re, stat, subprocess, tempfile, sqlite3, time, urllib.request
from pathlib import Path

HASH=re.compile(r'^[a-f0-9]{64}$')
RECOVERY_SCOPE='fs-navigation-recovery-20261015'
RECOVERY_TARGETS={'fs-home/navigation.json': '/var/www/dashboard/fs-home/navigation.json', 'hubnav.js': '/var/www/hub/hubnav.js', 'modules/arpg/index.html': '/var/www/dashboard/modules/arpg/index.html', 'modules/bots/index.html': '/var/www/dashboard/modules/bots/index.html', 'brain/index.html': '/var/www/dashboard/fs-home/brain/index.html'}
REVISION_UI_SCOPE='fs-revision-ui-20261015'
REVISION_UI_TARGETS={
 'revision/navigation.json':'/var/www/dashboard/fs-home/navigation.json',
 'revision/navigation.css':'/var/www/dashboard/fs-home/navigation.css',
 'revision/hubnav.css':'/var/www/dashboard/fs-home/hubnav.css',
 'revision/hubnav.js':'/var/www/hub/hubnav.js',
 **{'revision/modules/'+key+'/index.html':'/var/www/dashboard/modules/'+key+'/index.html' for key in ('analytics','sports')},
 **{'revision/brain/'+name:'/var/www/dashboard/fs-home/brain/'+name for name in ('index.html','brain.js','brain.css')},
}
RELATIVE={
 'fs-home/index.html','fs-home/navigation.js','fs-home/navigation.css','fs-home/navigation.json',
 'hubnav.js','hubnav.css',
 *(f'modules/{key}/index.html' for key in ('analytics','sports','arpg','collaboration','about')),
 *(f'analytics/{key}' for key in ('index.html','shell.js','shell.css','frame-theme.css')),
}
GREEN_TARGETS={
 'backend/taskboard_server.py':'/opt/mmoexp-taskboard/taskboard_server.py',
 'backend/green_plan.py':'/opt/mmoexp-taskboard/green_plan.py',
 'backend/green-plan-seed.json':'/opt/mmoexp-taskboard/green-plan-seed.json',
 'fs-home/navigation.json':'/var/www/dashboard/fs-home/navigation.json',
 **{'web/'+n:'/var/www/dashboard/tasks/green-plan/'+n for n in ('index.html','app.js','style.css','plan.html','plan.css','plan.js')},
}
GREEN_FIX_SCOPE='green-plan-review-fix-20261009'
GREEN_FIX_TARGETS={
 'auth/route-contract.json':'/opt/auth-portal/registration-runtime/20261007-ca6258ad/route-contract.json',
 'auth/native_access_policy.py':'/opt/auth-portal/registration-runtime/20261007-ca6258ad/vendor/native_access_policy.py',
 'auth/access_policy.py':'/opt/fs-access-policy/access_policy.py',
 **{'web/'+n:'/var/www/dashboard/tasks/green-plan/'+n for n in ('app.js','index.html')},
}
PERMISSION_SCOPE='registration-account-management-20261009'
PERMISSION_TARGETS={
 **{'permission-web/'+n:'/opt/auth-portal/registration-runtime/20261007-ca6258ad/web/'+n for n in ('app.js','index.html','access.css')},
 **{'permission-runtime/'+n:'/opt/auth-portal/registration-runtime/20261007-ca6258ad/'+n for n in ('runtime.py','module_permissions.py','consumer_seams.py','vendor/auth_candidate.py')},
 'permission-taskboard/taskboard_server.py':'/opt/mmoexp-taskboard/taskboard_server.py',
}
ACCOUNT_SCOPE='fs-account-management-20261015'
ACCOUNT_TARGETS={'account-runtime/'+name:'/opt/auth-portal/registration-runtime/20261007-ca6258ad/'+name for name in ('runtime.py','module_permissions.py','consumer_seams.py','vendor/auth_candidate.py','portal_bridge.py','account_management.py','web/app.js','web/index.html','web/access.css')}
AI_REVISION_SCOPE='fs-revision-ai-20261015'
AI_REVISION_TARGETS={
 **{'revision-ai/range/'+name:'/opt/fs-exact-range-20261001/'+name for name in ('fc_daily.py','fc_daily_model.py','ai_advisor_model.py','ai_advisor.py','fc_detail.py','range_api.py','profit_queries.py','fs_cleanup.py')},
 **{'revision-ai/boss/'+name:'/opt/fs-boss-workspaces/backend/'+name for name in ('boss_daily.py','game_intelligence.py','management_daily.py','workspace_official_model.py')},
 **{'revision-ai/hermes/'+name:'/opt/fs-hermes-fc/'+name for name in ('report_artifacts.py','boss_projection.py','boss_renderer.py','report.template.html')},
 **{'revision-ai/knowledge/'+name:'/opt/fs-hermes-fc/assets/'+name for name in ('knowledge-derived.md','knowledge-derived.json')},
 **{'revision-ai/units/'+name:'/etc/systemd/system/'+name for name in ('fs-maintenance-cleanup.service','fs-maintenance-cleanup.timer')},
}
AI_REVISION_NEW={'revision-ai/range/fs_cleanup.py','revision-ai/boss/workspace_official_model.py','revision-ai/hermes/boss_projection.py','revision-ai/hermes/boss_renderer.py','revision-ai/hermes/report.template.html','revision-ai/units/fs-maintenance-cleanup.service','revision-ai/units/fs-maintenance-cleanup.timer'}
AI_REVISION_BOSS_UNITS=('fs-boss-game-monitor.service','fs-boss-management.service')
AI_REVISION_CLEAN_UNITS=('fs-maintenance-cleanup.service','fs-maintenance-cleanup.timer')
QUERY_SCOPE='fs-internal-query-api-20261009'
QUERY_TARGETS={
 'query_api.py':'/opt/fs-query-api/query_api.py',
 'clients.json':'/etc/fs-query-api/clients.json',
 'fs-query-api.service':'/etc/systemd/system/fs-query-api.service',
 'range.locations.conf':'/etc/nginx/fs-business-range.locations.conf',
}

TRAFFIC_SCOPE='fs-traffic-member-20261009'
TRAFFIC_TARGETS={'custom_range.py': '/opt/mmoexp-marketing/custom-range/custom_range.py', 'range_api.py': '/opt/mmoexp-marketing/custom-range/range_api.py', 'session/admin_links.py': '/opt/fc27-cloud/marketing-session-20261009/admin_links.py', 'session/p2pah_session_service.py': '/opt/fc27-cloud/marketing-session-20261009/p2pah_session_service.py', 'session/Dockerfile.session': '/opt/fc27-cloud/marketing-session-20261009/Dockerfile.session', 'fs-marketing-range.service': '/etc/systemd/system/fs-marketing-range.service', 'fc27-p2pah-session.service': '/etc/systemd/system/fc27-p2pah-session.service', 'traffic-auth/runtime.py': '/opt/auth-portal/registration-runtime/20261007-ca6258ad/runtime.py', 'traffic-auth/route-contract.json': '/opt/auth-portal/registration-runtime/20261007-ca6258ad/route-contract.json'}

LIVE_SCOPE='fs-business-live-20261010'
LIVE_TARGETS={'live/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'live/live_summary.py': '/opt/fs-exact-range-20261001/live_summary.py', 'live/summary_bridge.py': '/opt/fs-exact-range-20261001/summary_bridge.py', 'session/p2pah_session_service.py': '/opt/fc27-cloud/marketing-session-20261009/p2pah_session_service.py', 'session/admin_summary.py': '/opt/fc27-cloud/marketing-session-20261009/admin_summary.py', 'session/supplement_fields.py': '/opt/fc27-cloud/marketing-session-20261009/supplement_fields.py', 'session/Dockerfile.session': '/opt/fc27-cloud/marketing-session-20261009/Dockerfile.session', 'fc27-p2pah-session.service': '/etc/systemd/system/fc27-p2pah-session.service'}

CACHE_FIX_SCOPE='fs-business-live-stale-20261010'

GAMES_SCOPE='fs-game-dashboards-20261012'
GAMES_TARGETS={'games/collector.py':'/opt/fs-transaction-snapshot/collector.py','games/admin_summary.py':'/opt/fc27-cloud/marketing-session-20261009/admin_summary.py'}

DEMAND_SCOPE='fs-on-demand-20261012'
DEMAND_TARGETS={'live/range_api.py':'/opt/fs-exact-range-20261001/range_api.py',
 'live/live_summary.py':'/opt/fs-exact-range-20261001/live_summary.py',
 'live/summary_bridge.py':'/opt/fs-exact-range-20261001/summary_bridge.py',
 'live/catalog.py':'/opt/fs-exact-range-20261001/catalog.py',
 'live/profit_queries.py':'/opt/fs-exact-range-20261001/profit_queries.py',
 'machine/query_api.py':'/opt/fs-query-api/query_api.py',
 'machine/clients.json':'/etc/fs-query-api/clients.json',
 'weekly/range_adapter.py':'/opt/mmoexp-weekly-report/src/range_adapter.py',
 'weekly/run_weekly_exact.py':'/opt/mmoexp-weekly-report/src/run_weekly_exact.py'}

BOUNDARY_SCOPE='fs-on-demand-boundary-20261012'
DETAIL_SCOPE='fc-detail-analytics-20261012'
DEEP_SCOPE='fc-deep-verified-facts-20261013'
HERMES_SCOPE='hermes-fc-readonly-20261013'
HERMES_UPDATE_SCOPE='hermes-fc-diagnostics-update-20261014'
HERMES_SECRET_SCOPE='hermes-fc-sk-text-guard-20261014'
HERMES_WIRE_SCOPE='hermes-fc-agent-wire-capacity-20261014'
HERMES_CAPACITY_SCOPE='hermes-fc-vendor-max-capacity-20261014'
HERMES_WORKER_SCOPE='hermes-fc-tool-result-update-20261014'
HERMES_HISTORY_SCOPE='hermes-fc-history-pagination-20261014'
HERMES_REPORT_SCOPE='hermes-fc-report-quality-html-20261014'
HERMES_QUALITY_SCOPE='hermes-report-semantic-quality-20261015'
HERMES_QUALITY_TARGETS={'report-quality/boss_projection.py':'/opt/fs-hermes-fc/boss_projection.py','report-quality/boss_renderer.py':'/opt/fs-hermes-fc/boss_renderer.py','report-quality/report_artifacts.py':'/opt/fs-hermes-fc/report_artifacts.py','report-quality/report_delivery.py':'/opt/fs-hermes-fc/report_delivery.py','report-quality/skill_bundle.py':'/opt/fs-hermes-fc/skill_bundle.py','report-quality/research.py':'/opt/fs-hermes-fc/research.py','report-quality/skills/manifest.json':'/opt/fs-hermes-fc/skills/manifest.json','report-quality/skills/fs-fc-operations-analysis/SKILL.md':'/opt/fs-hermes-fc/skills/fs-fc-operations-analysis/SKILL.md','report-quality/report_semantics.py':'/opt/fs-hermes-fc/report_semantics.py','report-quality/skills/fs-fc-operations-analysis/references/report-contract.md':'/opt/fs-hermes-fc/skills/fs-fc-operations-analysis/references/report-contract.md'}
HERMES_QUALITY_NEW={'report-quality/report_semantics.py','report-quality/skills/fs-fc-operations-analysis/references/report-contract.md'}
HERMES_PROOF_SCOPE='hermes-report-proof-guards-20261015'
HERMES_PROOF_TARGETS={k.replace('report-quality/','report-proof/'):v for k,v in HERMES_QUALITY_TARGETS.items()}
HERMES_PROOF_TARGETS['report-proof/report_constraints.py']='/opt/fs-hermes-fc/report_constraints.py'
HERMES_PROOF_NEW={'report-proof/report_constraints.py'}

def quality_targets(manifest):return HERMES_PROOF_TARGETS if manifest.get('scope')==HERMES_PROOF_SCOPE else HERMES_QUALITY_TARGETS
def quality_new(manifest):return HERMES_PROOF_NEW if manifest.get('scope')==HERMES_PROOF_SCOPE else HERMES_QUALITY_NEW


HERMES_CONTINUE_SCOPE='hermes-fc-frozen-evidence-continuation-20261014'
HERMES_AUTO_SCOPE='hermes-fc-autonomous-report-recovery-20261014'
HERMES_NIGHT_SCOPE='hermes-fc-nightly-window-20261014'
HERMES_TARGETS={'hermes/shared/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'hermes/shared/ai_advisor_model.py': '/opt/fs-exact-range-20261001/ai_advisor_model.py', 'hermes/fs-hermes-fc.service': '/etc/systemd/system/fs-hermes-fc.service', 'hermes/hermes.conf': '/etc/systemd/system/fs-business-range.service.d/hermes.conf', 'hermes/index.html': '/var/www/dashboard/fs-home/hermes/index.html', 'hermes/runtime/pilot.py': '/opt/fs-hermes-fc/pilot.py', 'hermes/runtime/runs_contract.py': '/opt/fs-hermes-fc/runs_contract.py', 'hermes/runtime/proxy_gateway.py': '/opt/fs-hermes-fc/proxy_gateway.py', 'hermes/runtime/transport.py': '/opt/fs-hermes-fc/transport.py', 'hermes/runtime/controller.py': '/opt/fs-hermes-fc/controller.py', 'hermes/runtime/fs_inprocess.py': '/opt/fs-hermes-fc/fs_inprocess.py', 'hermes/runtime/fs_evidence.py': '/opt/fs-hermes-fc/fs_evidence.py', 'hermes/runtime/research.py': '/opt/fs-hermes-fc/research.py', 'hermes/runtime/report_validation.py': '/opt/fs-hermes-fc/report_validation.py', 'hermes/runtime/background.py': '/opt/fs-hermes-fc/background.py', 'hermes/runtime/skill_bundle.py': '/opt/fs-hermes-fc/skill_bundle.py', 'hermes/runtime/hermes_worker.py': '/opt/fs-hermes-fc/hermes_worker.py', 'hermes/runtime/network_guard.py': '/opt/fs-hermes-fc/network_guard.py', 'hermes/runtime/runtime-config.yaml': '/opt/fs-hermes-fc/runtime-config.yaml', 'hermes/runtime/source_projection.py': '/opt/fs-hermes-fc/source_projection.py', 'hermes/runtime/skills/manifest.json': '/opt/fs-hermes-fc/skills/manifest.json', 'hermes/runtime/skills/fs-fc-operations-analysis/SKILL.md': '/opt/fs-hermes-fc/skills/fs-fc-operations-analysis/SKILL.md', 'hermes/runtime/skills/upstream/anthropic/LICENSE': '/opt/fs-hermes-fc/skills/upstream/anthropic/LICENSE', 'hermes/runtime/skills/upstream/hermes/LICENSE': '/opt/fs-hermes-fc/skills/upstream/hermes/LICENSE', 'hermes/runtime/skills/upstream/hermes/skills/research/grounded-citations/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/hermes/skills/research/grounded-citations/SKILL.md', 'hermes/runtime/skills/upstream/hermes/skills/productivity/xlsx/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/hermes/skills/productivity/xlsx/SKILL.md', 'hermes/runtime/skills/upstream/anthropic/data/skills/data-visualization/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/anthropic/data/skills/data-visualization/SKILL.md', 'hermes/runtime/skills/upstream/anthropic/data/skills/explore-data/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/anthropic/data/skills/explore-data/SKILL.md', 'hermes/runtime/skills/upstream/anthropic/data/skills/statistical-analysis/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/anthropic/data/skills/statistical-analysis/SKILL.md', 'hermes/runtime/skills/upstream/anthropic/data/skills/validate-data/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/anthropic/data/skills/validate-data/SKILL.md', 'hermes/runtime/skills/fs-fc-operations-analysis/references/methods.md': '/opt/fs-hermes-fc/skills/fs-fc-operations-analysis/references/methods.md', 'hermes/runtime/skills/fs-fc-operations-analysis/references/metric-governance.md': '/opt/fs-hermes-fc/skills/fs-fc-operations-analysis/references/metric-governance.md', 'hermes/runtime/assets/knowledge-derived.json': '/opt/fs-hermes-fc/assets/knowledge-derived.json', 'hermes/runtime/assets/knowledge-derived.md': '/opt/fs-hermes-fc/assets/knowledge-derived.md'}
HERMES_UPDATE_TARGETS={k:HERMES_TARGETS[k] for k in ('hermes/shared/ai_advisor_model.py','hermes/runtime/proxy_gateway.py','hermes/runtime/controller.py','hermes/runtime/fs_inprocess.py','hermes/index.html')}
HERMES_WIRE_TARGETS={k:HERMES_TARGETS[k] for k in ('hermes/shared/ai_advisor_model.py','hermes/runtime/proxy_gateway.py','hermes/runtime/transport.py','hermes/runtime/hermes_worker.py','hermes/runtime/fs_inprocess.py','hermes/runtime/runtime-config.yaml','hermes/runtime/controller.py','hermes/index.html')}
HERMES_SECRET_TARGETS={k:HERMES_TARGETS[k] for k in ('hermes/runtime/proxy_gateway.py','hermes/runtime/report_validation.py','hermes/runtime/controller.py','hermes/runtime/background.py','hermes/runtime/pilot.py','hermes/runtime/research.py')}
HERMES_WORKER_TARGETS={'hermes/runtime/hermes_worker.py':HERMES_TARGETS['hermes/runtime/hermes_worker.py']}
HERMES_HISTORY_TARGETS={k:HERMES_TARGETS[k] for k in ('hermes/runtime/fs_evidence.py','hermes/runtime/research.py','hermes/runtime/controller.py')}
HERMES_DIRECT_SCOPE='hermes-fc-deepseek-direct-20261014'
HERMES_CAPABILITY_SCOPE='hermes-fc-admin-order-capabilities-20261014'
CAP_SESSION_ROOT='/opt/fc27-cloud/marketing-session-20261009'
CAP_SESSION_TAG='fc27-cloud-session:business-live-20261010'
CAP_SESSION_BASE_TAG='fc27-cloud-session:traffic-20261009-ec4c7ba41c3c'
CAP_FS_PACKAGE=('__init__.py','capabilities.py','admin_session_entry.py','fs_reader.py','order_detail_projection.py','provider.py')
CAP_SESSION_PACKAGE=('__init__.py','capabilities.py','admin_session_entry.py')
HERMES_CAPABILITY_TARGETS={
 **{k:HERMES_TARGETS[k] for k in ('hermes/runtime/fs_evidence.py','hermes/runtime/research.py')},
 'capability/session/p2pah_session_service.py':CAP_SESSION_ROOT+'/p2pah_session_service.py',
 'capability/session/Dockerfile.session':CAP_SESSION_ROOT+'/Dockerfile.session',
 'capability/order/fc_order_reader.py':'/opt/fs-exact-range-20261001/fc_order_reader.py',
 **{'capability/fs-package/'+n:'/opt/fs-hermes-fc/admin_order_capabilities_20261014/'+n for n in CAP_FS_PACKAGE},
 **{'capability/session-package/'+n:CAP_SESSION_ROOT+'/admin_order_capabilities_20261014/'+n for n in CAP_SESSION_PACKAGE},
}
HERMES_CAPACITY_TARGETS={**HERMES_WIRE_TARGETS, 'hermes/runtime/research.py':HERMES_TARGETS['hermes/runtime/research.py'], 'hermes/runtime/fs_evidence.py':HERMES_TARGETS['hermes/runtime/fs_evidence.py'], 'capability/fs-package/provider.py':HERMES_CAPABILITY_TARGETS['capability/fs-package/provider.py']}
HERMES_DIRECT_TARGETS={**{k:HERMES_TARGETS[k] for k in ('hermes/runtime/proxy_gateway.py','hermes/runtime/controller.py','hermes/runtime/fs_inprocess.py','hermes/runtime/hermes_worker.py','hermes/runtime/runtime-config.yaml','hermes/index.html')}, 'hermes/runtime/direct_provider.py':'/opt/fs-hermes-fc/direct_provider.py'}
HERMES_REPORT_TARGETS={**{k:HERMES_TARGETS[k] for k in ('hermes/runtime/controller.py','hermes/runtime/report_validation.py','hermes/index.html','hermes/runtime/skills/manifest.json','hermes/runtime/skills/fs-fc-operations-analysis/SKILL.md')},'hermes/runtime/report_html.py':'/opt/fs-hermes-fc/report_html.py'}
HERMES_CONTINUE_TARGETS={**{k:HERMES_TARGETS[k] for k in ('hermes/runtime/controller.py','hermes/index.html')},'hermes/runtime/continuation.py':'/opt/fs-hermes-fc/continuation.py'}
HERMES_AUTO_TARGETS={**{k:HERMES_TARGETS[k] for k in ('hermes/runtime/controller.py','hermes/runtime/proxy_gateway.py','hermes/runtime/transport.py','hermes/runtime/fs_inprocess.py','hermes/index.html','hermes/runtime/skills/manifest.json','hermes/runtime/skills/fs-fc-operations-analysis/SKILL.md')},**{'hermes/runtime/'+n:'/opt/fs-hermes-fc/'+n for n in ('continuation.py','report_html.py','report_artifacts.py','report_delivery.py')}}
HERMES_NIGHT_TARGETS={**{'hermes/runtime/'+n:'/opt/fs-hermes-fc/'+n for n in ('controller.py','direct_provider.py','fs_inprocess.py','fs_evidence.py','runs_contract.py','nightly.py','background.py','hermes_worker.py')},
 'hermes/index.html':'/var/www/dashboard/fs-home/hermes/index.html',
 **{'hermes/runtime/assets/'+n:'/opt/fs-hermes-fc/assets/'+n for n in ('knowledge-derived.md','knowledge-derived.json')},
 **{'hermes/nightly/'+n:'/opt/fs-boss-workspaces/backend/'+n for n in ('game_intelligence.py','management_daily.py','nightly_http.py')},
 'hermes/runtime/nightly_http.py':'/opt/fs-hermes-fc/nightly_http.py',
 'hermes/nightly/boss_daily.py':'/opt/fs-boss-workspaces/backend/boss_daily.py',
 'hermes/nightly/server_run_integrated.py':'/opt/mmoexp-marketing/deployment/server_run_integrated.py',
 **{'hermes/nightly/'+n:'/etc/systemd/system/'+n for n in ('fs-boss-game-monitor.timer','fs-boss-management.timer','mmoexp-marketing-daily.timer','mmoexp-marketing-daily.service')},
 'hermes/nightly/nightly-schedule.json':'/var/lib/fs-hermes-fc/fs/nightly-schedule.json'}
HERMES_NIGHT_TARGETS.update({'hermes/runtime/skill_bundle.py': '/opt/fs-hermes-fc/skill_bundle.py', 'hermes/runtime/skills/manifest.json': '/opt/fs-hermes-fc/skills/manifest.json', 'hermes/runtime/skills/upstream/reviewed/marketing-LICENSE': '/opt/fs-hermes-fc/skills/upstream/reviewed/marketing-LICENSE', 'hermes/runtime/skills/upstream/reviewed/ab-testing/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/ab-testing/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/attribution/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/attribution/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/customer-research/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/customer-research/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/humanizer-zh/LICENSE': '/opt/fs-hermes-fc/skills/upstream/reviewed/humanizer-zh/LICENSE', 'hermes/runtime/skills/upstream/reviewed/humanizer-zh/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/humanizer-zh/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/marketing-psychology/SKILL.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/marketing-psychology/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/customer-research/references/interviews-and-surveys.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/customer-research/references/interviews-and-surveys.md', 'hermes/runtime/skills/upstream/reviewed/customer-research/references/source-guides.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/customer-research/references/source-guides.md', 'hermes/runtime/skills/upstream/reviewed/attribution/references/attribution-models.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/attribution/references/attribution-models.md', 'hermes/runtime/skills/upstream/reviewed/attribution/references/by-business-type.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/attribution/references/by-business-type.md', 'hermes/runtime/skills/upstream/reviewed/attribution/references/measurement-paradigms.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/attribution/references/measurement-paradigms.md', 'hermes/runtime/skills/upstream/reviewed/ab-testing/references/sample-size-guide.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/ab-testing/references/sample-size-guide.md', 'hermes/runtime/skills/upstream/reviewed/ab-testing/references/test-templates.md': '/opt/fs-hermes-fc/skills/upstream/reviewed/ab-testing/references/test-templates.md', 'hermes/runtime/skills/fs-fc-operations-analysis/references/reviewed-adaptation.md': '/opt/fs-hermes-fc/skills/fs-fc-operations-analysis/references/reviewed-adaptation.md'})
NIGHT_TIMERS=('fs-boss-game-monitor.timer','fs-boss-management.timer','mmoexp-marketing-daily.timer')
CAP_EXISTING_TARGETS={k for k in HERMES_CAPABILITY_TARGETS if '/fs-package/' not in k and '/session-package/' not in k}
CAP_PROTECTED_SESSION={CAP_SESSION_ROOT+'/admin_summary.py',CAP_SESSION_ROOT+'/supplement_fields.py','/etc/systemd/system/fc27-p2pah-session.service','/opt/fs-exact-range-20261001/fc_order_diagnostics.py'}

DEEP_TARGETS={'deep/fc_deep_model.py':'/opt/fs-exact-range-20261001/fc_deep_model.py'}
ADVISOR_SCOPE='fs-ai-advisor-20261013'
ADVISOR_TARGETS={'advisor/'+n:'/opt/fs-exact-range-20261001/'+n for n in ('range_api.py', 'fc_daily.py', 'ai_advisor.py', 'ai_advisor_model.py', 'boss_insights.py')}
DAILY_SCOPE='fc-daily-20261013'
DAILY_TARGETS={'daily/'+n:'/opt/fs-exact-range-20261001/'+n for n in ('range_api.py','fc_daily.py','fc_daily_model.py')}
DETAIL_TARGETS={'fc/'+name:'/opt/fs-exact-range-20261001/'+name for name in ('range_api.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json')}


HERMES_DESKTOP_SCOPE='hermes-desktop-full-20261015'
HERMES_DESKTOP_TARGETS={'desktop/serve.py': '/opt/fs-hermes-desktop/serve.py', 'desktop/fs-hermes-desktop.service': '/etc/systemd/system/fs-hermes-desktop.service', 'desktop/desktop-context-instructions.md': '/var/lib/fs-hermes-fc/profile/AGENTS.md', 'hermes/runtime/business_context.py': '/opt/fs-hermes-fc/business_context.py', 'hermes/runtime/controller.py': '/opt/fs-hermes-fc/controller.py'}

def expected_files(manifest):
 if manifest.get('scope') in (HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE):return set(quality_targets(manifest))
 if manifest.get('scope')==HERMES_DESKTOP_SCOPE:return set(HERMES_DESKTOP_TARGETS)
 if manifest.get('scope')==RECOVERY_SCOPE:return set(RECOVERY_TARGETS)
 if manifest.get('scope')==REVISION_UI_SCOPE:return set(REVISION_UI_TARGETS)
 if manifest.get('scope')==AI_REVISION_SCOPE:return set(AI_REVISION_TARGETS)
 if manifest.get('scope')==ACCOUNT_SCOPE:return set(ACCOUNT_TARGETS)
 if manifest.get('scope')==HERMES_NIGHT_SCOPE:return set(HERMES_NIGHT_TARGETS)
 if manifest.get('scope')==HERMES_CONTINUE_SCOPE:return set(HERMES_CONTINUE_TARGETS)
 if manifest.get('scope')==HERMES_AUTO_SCOPE:return set(HERMES_AUTO_TARGETS)
 if manifest.get('scope')==HERMES_REPORT_SCOPE:return set(HERMES_REPORT_TARGETS)
 if manifest.get('scope')==HERMES_DIRECT_SCOPE:return set(HERMES_DIRECT_TARGETS)
 if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:return set(HERMES_CAPABILITY_TARGETS)
 if manifest.get('scope')==HERMES_SECRET_SCOPE:return set(HERMES_SECRET_TARGETS)
 if manifest.get('scope')==HERMES_HISTORY_SCOPE:return set(HERMES_HISTORY_TARGETS)
 if manifest.get('scope')==HERMES_WIRE_SCOPE:return set(HERMES_WIRE_TARGETS)
 if manifest.get('scope')==HERMES_CAPACITY_SCOPE:return set(HERMES_CAPACITY_TARGETS)
 if manifest.get('scope')==HERMES_WORKER_SCOPE:return set(HERMES_WORKER_TARGETS)
 if manifest.get('scope')==HERMES_UPDATE_SCOPE:return set(HERMES_UPDATE_TARGETS)
 if manifest.get('scope')==HERMES_SCOPE:return set(HERMES_TARGETS)
 if manifest.get("scope")==DEEP_SCOPE:return set(DEEP_TARGETS)
 if manifest.get("scope")==ADVISOR_SCOPE:return set(ADVISOR_TARGETS)
 if manifest.get("scope")==DAILY_SCOPE:return set(DAILY_TARGETS)
 if manifest.get("scope")==DETAIL_SCOPE:return set(DETAIL_TARGETS)
 if manifest.get('scope')==BOUNDARY_SCOPE:return {'live/range_api.py'}
 if manifest.get('scope')==DEMAND_SCOPE:return set(DEMAND_TARGETS)
 if manifest.get('scope')==GAMES_SCOPE:return set(GAMES_TARGETS)
 if manifest.get('scope')==CACHE_FIX_SCOPE:return {'live/live_summary.py'}
 if manifest.get('scope') in (LIVE_SCOPE,CACHE_FIX_SCOPE):return set(LIVE_TARGETS)
 if manifest.get("scope")==TRAFFIC_SCOPE:return set(TRAFFIC_TARGETS)
 if manifest.get("scope")==QUERY_SCOPE:return set(QUERY_TARGETS)
 if manifest.get('scope')==PERMISSION_SCOPE:return set(PERMISSION_TARGETS)
 if manifest.get('scope')==GREEN_FIX_SCOPE:return set(GREEN_FIX_TARGETS)
 return set(GREEN_TARGETS) if manifest.get('scope')=='green-plan-20261009' else RELATIVE

def target_for(rel):
 if rel in HERMES_PROOF_TARGETS:return HERMES_PROOF_TARGETS[rel]
 if rel in HERMES_QUALITY_TARGETS:return HERMES_QUALITY_TARGETS[rel]
 if rel in HERMES_DESKTOP_TARGETS:return HERMES_DESKTOP_TARGETS[rel]
 if rel in RECOVERY_TARGETS:return RECOVERY_TARGETS[rel]
 if rel in REVISION_UI_TARGETS:return REVISION_UI_TARGETS[rel]
 if rel in AI_REVISION_TARGETS:return AI_REVISION_TARGETS[rel]
 if rel in ACCOUNT_TARGETS:return ACCOUNT_TARGETS[rel]
 if rel in HERMES_NIGHT_TARGETS:return HERMES_NIGHT_TARGETS[rel]
 if rel in HERMES_CONTINUE_TARGETS:return HERMES_CONTINUE_TARGETS[rel]
 if rel in HERMES_AUTO_TARGETS:return HERMES_AUTO_TARGETS[rel]
 if rel in HERMES_REPORT_TARGETS:return HERMES_REPORT_TARGETS[rel]
 if rel in HERMES_DIRECT_TARGETS:return HERMES_DIRECT_TARGETS[rel]
 if rel in HERMES_CAPABILITY_TARGETS:return HERMES_CAPABILITY_TARGETS[rel]
 if rel in HERMES_TARGETS:return HERMES_TARGETS[rel]
 if rel in DEEP_TARGETS:return DEEP_TARGETS[rel]
 if rel in ADVISOR_TARGETS:return ADVISOR_TARGETS[rel]
 if rel in DAILY_TARGETS:return DAILY_TARGETS[rel]
 if rel in DETAIL_TARGETS:return DETAIL_TARGETS[rel]
 if rel in DEMAND_TARGETS:return DEMAND_TARGETS[rel]
 if rel in GAMES_TARGETS:return GAMES_TARGETS[rel]
 if rel in LIVE_TARGETS:return LIVE_TARGETS[rel]
 if rel in TRAFFIC_TARGETS:return TRAFFIC_TARGETS[rel]
 if rel in QUERY_TARGETS:return QUERY_TARGETS[rel]
 if rel in PERMISSION_TARGETS:return PERMISSION_TARGETS[rel]
 if rel in GREEN_FIX_TARGETS:return GREEN_FIX_TARGETS[rel]
 if rel in GREEN_TARGETS:return GREEN_TARGETS[rel]
 if rel not in RELATIVE: raise ValueError('unapproved candidate file')
 return '/var/www/hub/'+rel if rel in ('hubnav.js','hubnav.css') else '/var/www/dashboard/'+rel
def rooted(root,path): return root/path.lstrip('/')
def digest(path):
 return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
def directory_sync(path):
 fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
 try:os.fsync(fd)
 finally:os.close(fd)
def no_target_link(path):
 for p in (path,*path.parents):
  if p.is_symlink():raise ValueError('target or parent is a symlink: '+str(p))
 if path.exists() and not path.is_file():raise ValueError('target is not a regular file')
def atomic(path,data,mode=0o644):
 no_target_link(path)
 path.parent.mkdir(parents=True,exist_ok=True)
 no_target_link(path)
 fd,tmp=tempfile.mkstemp(prefix='.fs-nav-',dir=str(path.parent))
 try:
  with os.fdopen(fd,'wb') as f:
   f.write(data);f.flush()
   if hasattr(os,'fchmod'):os.fchmod(f.fileno(),mode)
   else:os.chmod(tmp,mode)
   os.fsync(f.fileno())
  os.replace(tmp,path);directory_sync(path.parent)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def validate(manifest,stage):
 files=manifest.get('files',[])
 expected=expected_files(manifest)
 if manifest.get('schemaVersion')!=1 or {f.get('candidate') for f in files}!=expected or len(files)!=len(expected):raise ValueError('manifest must contain the exact approved scope')
 for row in files:
  rel=row['candidate'];src=stage/'candidate'/rel
  if row.get('target')!=target_for(rel) or not HASH.fullmatch(row.get('sha256','')):raise ValueError('invalid target or hash')
  if row.get('beforeSha256') is not None and not HASH.fullmatch(row['beforeSha256']):raise ValueError('invalid baseline hash')
  if manifest.get('scope') in (HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE) and (rel in quality_new(manifest))!=(row.get('beforeSha256') is None):raise ValueError('exact report quality existing/new baselines required')
  if manifest.get('scope')==RECOVERY_SCOPE and (row.get('beforeSha256') is None)!=(rel=='modules/bots/index.html'):raise ValueError('exact recovery baseline required')
  if manifest.get('scope')==AI_REVISION_SCOPE and rel not in AI_REVISION_NEW and row.get('beforeSha256') is None:raise ValueError('existing AI revision baseline required')
  if manifest.get('scope')==REVISION_UI_SCOPE and not rel.startswith('revision/brain/') and row.get('beforeSha256') is None:raise ValueError('existing navigation baseline required')
  if manifest.get('scope')==ACCOUNT_SCOPE and rel!='account-runtime/account_management.py' and row.get('beforeSha256') is None:raise ValueError('existing account target baseline required')
  if manifest.get('scope')==GREEN_FIX_SCOPE and row.get('beforeSha256') is None:raise ValueError('review-fix existing target baseline required')
  if manifest.get('scope')==PERMISSION_SCOPE and rel!='permission-runtime/module_permissions.py' and row.get('beforeSha256') is None:raise ValueError('existing permission target baseline required')
  if manifest.get('scope')=='green-plan-20261009' and rel in ('backend/taskboard_server.py','fs-home/navigation.json') and row.get('beforeSha256') is None:raise ValueError('existing green-plan consumer baseline required')
  if manifest.get('scope') in (GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE) and rel not in ('live/catalog.py','live/profit_queries.py') and row.get('beforeSha256') is None:raise ValueError('existing game target baseline required')
  if src.is_symlink() or (stage/'candidate').resolve() not in src.resolve().parents:raise ValueError('candidate escaped stage')
  if digest(src)!=row['sha256']:raise ValueError('staged candidate SHA differs from reviewed manifest')
 if manifest.get('scope')==AI_REVISION_SCOPE:
  if manifest.get('runtimeRequired',{}).get('fs-business-range.service')!={'ActiveState':'active'} or manifest.get('cleanupActivationDuringRelease') is not False:raise ValueError('active range and deferred cleanup activation required')
  service=(stage/'candidate/revision-ai/units/fs-maintenance-cleanup.service').read_text()
  timer=(stage/'candidate/revision-ai/units/fs-maintenance-cleanup.timer').read_text()
  if [line for line in service.splitlines() if line.startswith('ExecStart=')]!=['ExecStart=/opt/python39/bin/python3 -B /opt/fs-exact-range-20261001/fs_cleanup.py --apply']:raise ValueError('exact deferred cleanup service required')
  if not all(line in timer.splitlines() for line in ('OnCalendar=*-*-* 06:30:00','Persistent=false','Unit=fs-maintenance-cleanup.service')):raise ValueError('exact nonpersistent cleanup timer required')
 if manifest.get('scope')==ACCOUNT_SCOPE and manifest.get('runtimeRequired',{}).get('auth-portal.service')!={'ActiveState':'active'}:raise ValueError('account release requires active auth service')
 if manifest.get('scope')==GREEN_FIX_SCOPE and manifest.get('runtimeRequired',{}).get('auth-portal.service')!={'ActiveState':'active'}:raise ValueError('review-fix requires active auth service without PID pinning')
 if manifest.get('scope')==PERMISSION_SCOPE and manifest.get('runtimeRequired',{}).get('auth-portal.service')!={'ActiveState':'active'}:raise ValueError('permission release requires active auth service')
 if manifest.get('scope')==QUERY_SCOPE:
  for row in files:
   if row['candidate']=='range.locations.conf':
    if not HASH.fullmatch(row.get('beforeSha256') or ''):raise ValueError('existing range route baseline required')
   elif row.get('beforeSha256') is not None:raise ValueError('first API release requires absent targets')
  clients=json.loads((stage/'candidate/clients.json').read_text())['clients']
  if len(clients)!=1 or clients[0]['id']!='dy-all-projects' or clients[0]['owner']!='DY' or clients[0]['includeProfit'] is not True or not HASH.fullmatch(clients[0]['tokenSha256']):raise ValueError('DY exact scope required')
  if set(clients[0]['projects'])!={'AION2','CFB27','D4','FC26','FC27','MLB26','MMOEXP','NBA2K27','NFL27','POE2'}:raise ValueError('project scope differs')
 if manifest.get('scope')==TRAFFIC_SCOPE:
  if manifest.get('sessionBaseImage')!='sha256:42d53d8c606491685f8a87db7bf6b0d1010c855464c37b8e37e7bbd45dd1dcda':raise ValueError('session image contract differs')
  for row in files:
   existing=row['candidate'] in ('fc27-p2pah-session.service','traffic-auth/runtime.py','traffic-auth/route-contract.json')
   if existing != (row.get('beforeSha256') is not None):raise ValueError('traffic first release target baseline differs')
 if manifest.get('scope') in (LIVE_SCOPE,CACHE_FIX_SCOPE):
  existing={'live/live_summary.py'} if manifest.get('scope')==CACHE_FIX_SCOPE else {'live/range_api.py','session/p2pah_session_service.py','session/Dockerfile.session','fc27-p2pah-session.service'}
  if any((row['candidate'] in existing)!=(row['beforeSha256'] is not None) for row in files):raise ValueError('live target baseline contract differs')
 if manifest.get('scope')==DETAIL_SCOPE:
  if next(r for r in files if r['candidate']=='fc/range_api.py')['beforeSha256'] is None:raise ValueError('active range baseline required')
  c=json.loads((stage/'candidate/fc/fc_detail_config.json').read_text())
  if c['game_id']!=1327 or c['main_site_id']!=266 or c['ai_enabled'] is not False:raise ValueError('FC-only no-AI config required')
 if manifest.get('scope')==DAILY_SCOPE:
  if next(r for r in files if r['candidate']=='daily/range_api.py')['beforeSha256'] is None:raise ValueError('existing range baseline required')
 if manifest.get('scope')==ADVISOR_SCOPE:
  for r in files:
   if (r['candidate'] in ('advisor/range_api.py','advisor/fc_daily.py')) != (r['beforeSha256'] is not None):raise ValueError('advisor exact baseline required')
  if manifest.get('runtimeRequired',{}).get('fs-business-range.service')!={'ActiveState':'active'}:raise ValueError('existing active range required')
 if manifest.get('scope')==DEEP_SCOPE:
  for r in files:
   if r['beforeSha256'] is None:raise ValueError('existing deep model baseline required')
  if manifest.get('runtimeRequired',{}).get('fs-business-range.service')!={'ActiveState':'active'}:raise ValueError('existing active range required')
 if manifest.get('scope')==HERMES_SCOPE:
  if manifest.get('runtimeRequired',{}).get('fs-business-range.service')!={'ActiveState':'active'}:raise ValueError('active original FS process required')
  existing={'hermes/shared/range_api.py','hermes/shared/ai_advisor_model.py'}
  if any((r['candidate'] in existing)!=(r.get('beforeSha256') is not None) for r in files):raise ValueError('Hermes initial target baselines differ')
  if manifest.get('imageId')!='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544':raise ValueError('fixed Hermes artifact required')
  if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:raise ValueError('Hermes readonly/schedule boundary')
 if manifest.get('scope') in (HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE):
  if any(r.get('beforeSha256') is None for r in files if not ((manifest.get('scope') in (HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE) and r['candidate'] in quality_new(manifest)) or (manifest.get('scope')==HERMES_AUTO_SCOPE and r['candidate'] in ('hermes/runtime/report_artifacts.py','hermes/runtime/report_delivery.py')) or (manifest.get('scope')==HERMES_CONTINUE_SCOPE and r['candidate']=='hermes/runtime/continuation.py') or (manifest.get('scope')==HERMES_DIRECT_SCOPE and r['candidate']=='hermes/runtime/direct_provider.py') or (manifest.get('scope')==HERMES_REPORT_SCOPE and r['candidate']=='hermes/runtime/report_html.py'))):raise ValueError('existing Hermes update baselines required')
  for unit in ('fs-business-range.service','fs-hermes-fc.service'):
   if manifest.get('runtimeRequired',{}).get(unit)!={'ActiveState':'active'}:raise ValueError('active Hermes update services required')
  if manifest.get('imageId')!='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544':raise ValueError('fixed Hermes artifact required')
  if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:raise ValueError('Hermes readonly/schedule boundary')
 if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:
  helper=stage/'capability_image_lifecycle.py'
  if helper.is_symlink() or not HASH.fullmatch(manifest.get('imageLifecycleSha256','')) or digest(helper)!=manifest['imageLifecycleSha256']:raise ValueError('frozen capability image lifecycle required')
  if any(r.get('beforeSha256') is None for r in files if r['candidate'] in CAP_EXISTING_TARGETS):raise ValueError('existing capability source baseline required')
  for unit in ('fs-business-range.service','fs-hermes-fc.service','fc27-p2pah-session.service'):
   if manifest.get('runtimeRequired',{}).get(unit)!={'ActiveState':'active'}:raise ValueError('active capability services required')
  if manifest.get('imageId')!='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544':raise ValueError('fixed Hermes artifact required')
  for key in ('sessionCurrentImage','sessionBaseImage'):
   if not re.fullmatch(r'sha256:[a-f0-9]{64}',manifest.get(key,'')):raise ValueError('pinned capability session image required')
  if not re.fullmatch(r'[a-f0-9]{40}',manifest.get('sourceCommit','')):raise ValueError('capability source commit required')
  if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:raise ValueError('capability readonly/schedule boundary')
  docker=(stage/'candidate/capability/session/Dockerfile.session').read_text('utf-8')
  if docker.splitlines()[0]!='FROM '+CAP_SESSION_BASE_TAG:raise ValueError('capability base Dockerfile differs')
  exact='COPY '+' '.join('admin_order_capabilities_20261014/'+n for n in CAP_SESSION_PACKAGE)+' /usr/local/bin/admin_order_capabilities_20261014/'
  if exact not in docker.splitlines() or any(line.startswith('COPY admin_order_capabilities_20261014 ') for line in docker.splitlines()):raise ValueError('exact three session package copies required')
  for n in CAP_SESSION_PACKAGE:
   if (stage/'candidate/capability/fs-package'/n).read_bytes()!=(stage/'candidate/capability/session-package'/n).read_bytes():raise ValueError('paired capability projection differs')
 if manifest.get('scope')==HERMES_NIGHT_SCOPE:
  if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not True:raise ValueError('nightly readonly scheduling approval required')
  if manifest.get('timezone')!='Asia/Shanghai' or manifest.get('imageId')!='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544':raise ValueError('nightly timezone/fixed image')
  new_targets={'hermes/runtime/nightly.py','hermes/runtime/nightly_http.py','hermes/nightly/nightly_http.py','hermes/nightly/nightly-schedule.json',*['hermes/runtime/skills/upstream/reviewed/marketing-LICENSE', 'hermes/runtime/skills/upstream/reviewed/ab-testing/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/attribution/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/customer-research/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/humanizer-zh/LICENSE', 'hermes/runtime/skills/upstream/reviewed/humanizer-zh/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/marketing-psychology/SKILL.md', 'hermes/runtime/skills/upstream/reviewed/customer-research/references/interviews-and-surveys.md', 'hermes/runtime/skills/upstream/reviewed/customer-research/references/source-guides.md', 'hermes/runtime/skills/upstream/reviewed/attribution/references/attribution-models.md', 'hermes/runtime/skills/upstream/reviewed/attribution/references/by-business-type.md', 'hermes/runtime/skills/upstream/reviewed/attribution/references/measurement-paradigms.md', 'hermes/runtime/skills/upstream/reviewed/ab-testing/references/sample-size-guide.md', 'hermes/runtime/skills/upstream/reviewed/ab-testing/references/test-templates.md', 'hermes/runtime/skills/fs-fc-operations-analysis/references/reviewed-adaptation.md']}
  if any((r.get('beforeSha256') is None)!=(r['candidate'] in new_targets) for r in files):raise ValueError('nightly exact first-release baseline')
  config=json.loads((stage/'candidate/hermes/nightly/nightly-schedule.json').read_text())
  if config!={'contract':'fs-hermes-nightly-v1','enabled':True,'owner':'wulv','timezone':'Asia/Shanghai'}:raise ValueError('nightly owner contract')
  if (stage/'candidate/hermes/runtime/nightly_http.py').read_bytes()!=(stage/'candidate/hermes/nightly/nightly_http.py').read_bytes():raise ValueError('paired deadline transport differs')
  if manifest.get('rollbackSchedulePolicy')!='pause_three_timers_without_replay':raise ValueError('nightly rollback policy')
  for name,clock in zip(NIGHT_TIMERS,('00:05:00','00:20:00','00:10:00')):
   text=(stage/'candidate/hermes/nightly'/name).read_text()
   if 'OnCalendar=*-*-* '+clock+'\n' not in text or 'Persistent=false\n' not in text or 'Persistent=true' in text:raise ValueError('nightly exact timer contract')
  for unit in ('fs-business-range.service','fs-hermes-fc.service','fc27-p2pah-session.service'):
   if manifest.get('runtimeRequired',{}).get(unit)!={'ActiveState':'active'}:raise ValueError('nightly runtime services')
  for unit in ('fs-boss-game-monitor.service','fs-boss-management.service','mmoexp-marketing-daily.service'):
   if manifest.get('runtimeRequired',{}).get(unit)!={'ActiveState':'inactive'}:raise ValueError('preparation must be idle')
 protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}
 if manifest.get('scope') in (HERMES_SCOPE,HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE):
  required={'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
  required|={'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
  targets=HERMES_AUTO_TARGETS if manifest.get('scope')==HERMES_AUTO_SCOPE else HERMES_CONTINUE_TARGETS if manifest.get('scope')==HERMES_CONTINUE_SCOPE else HERMES_REPORT_TARGETS if manifest.get('scope')==HERMES_REPORT_SCOPE else HERMES_SECRET_TARGETS if manifest.get('scope')==HERMES_SECRET_SCOPE else HERMES_CAPABILITY_TARGETS if manifest.get('scope')==HERMES_CAPABILITY_SCOPE else HERMES_HISTORY_TARGETS if manifest.get('scope')==HERMES_HISTORY_SCOPE else HERMES_WORKER_TARGETS if manifest.get('scope')==HERMES_WORKER_SCOPE else HERMES_DIRECT_TARGETS if manifest.get('scope')==HERMES_DIRECT_SCOPE else HERMES_CAPACITY_TARGETS if manifest.get('scope')==HERMES_CAPACITY_SCOPE else HERMES_WIRE_TARGETS if manifest.get('scope')==HERMES_WIRE_SCOPE else HERMES_UPDATE_TARGETS if manifest.get('scope')==HERMES_UPDATE_SCOPE else HERMES_TARGETS
  if manifest.get('scope')==HERMES_NIGHT_SCOPE:targets=HERMES_NIGHT_TARGETS
  if manifest.get('scope') in (HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE):targets=quality_targets(manifest)
  if manifest.get('scope') in (HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE):required|=set(HERMES_TARGETS.values())-set(targets.values())
  if manifest.get('scope') in (HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_SECRET_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE):required|=(set(HERMES_CAPABILITY_TARGETS.values())|CAP_PROTECTED_SESSION)-set(targets.values())
  if manifest.get('scope') in (HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE):required|=set(HERMES_DIRECT_TARGETS.values())-set(targets.values())
  if manifest.get('scope')==HERMES_CONTINUE_SCOPE:required|=set(HERMES_REPORT_TARGETS.values())-set(targets.values())
  if not required.issubset(protected) or set(protected)&set(targets.values()):raise ValueError('Hermes protected consumer boundary differs')
 if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:
  if not CAP_PROTECTED_SESSION.issubset(protected):raise ValueError('capability protected session dependencies required')
 if manifest.get('scope')==DEEP_SCOPE:
  required={'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','ai_advisor_model.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','summary_bridge.py')}
  required|={'/opt/fs-exact-range-20261001/'+n for n in ('range_api.py','fc_daily.py','ai_advisor.py','fc_deep_analysis.py','fc_deep_sources.py','fc_deep_service.py','advisor_memory.py','fc_order_diagnostics.py','fc_order_reader.py')}
  required|={'/opt/fs-access-policy/access_policy.py','/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js'}
  if not required.issubset(protected) or set(protected)&set(DEEP_TARGETS.values()):raise ValueError('deep dependency boundary differs')
 if manifest.get('scope')==DETAIL_SCOPE and set(protected)&set(DETAIL_TARGETS.values()):raise ValueError('FC target cannot also be unchanged')
 if manifest.get('scope') in (GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE) and set(protected)&set(GAMES_TARGETS.values() if manifest.get('scope')==GAMES_SCOPE else [DEMAND_TARGETS['live/range_api.py']] if manifest.get('scope')==BOUNDARY_SCOPE else DEMAND_TARGETS.values()):raise ValueError('game target cannot also be unchanged')
 if not HASH.fullmatch(protected.get('/var/www/dashboard/index.html','')):raise ValueError('protected business HTML SHA is required')
 return files
def approved_daily_group(manifest,root,item,info):
 return info.st_gid==0 or (manifest.get('scope')==HERMES_NIGHT_SCOPE and item==rooted(root,'/var/lib/fs-hermes-fc') and info.st_uid==0 and info.st_gid==9876 and stat.S_IMODE(info.st_mode)==0o750)

def revision_units_inactive(units):
 for unit in units:
  command=['systemctl','show',unit,'--no-pager','-p','ActiveState','-p','UnitFileState','-p','LoadState']
  if unit.endswith('.service'):command+=['-p','MainPID']
  result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
  props=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
  if any(name not in props for name in ('ActiveState','UnitFileState','LoadState')) or props['LoadState'] not in ('loaded','not-found'):raise ValueError('unknown revision consumer state; defer update: '+unit)
  allowed=props.get('ActiveState') in ('inactive','failed') if unit in AI_REVISION_BOSS_UNITS else props.get('ActiveState')=='inactive'
  if not allowed or (unit.endswith('.service') and props.get('MainPID')!='0') or (unit in AI_REVISION_CLEAN_UNITS and props.get('UnitFileState') in ('enabled','enabled-runtime')) or (result.returncode and props.get('LoadState')!='not-found'):raise ValueError('active/enabled revision consumer; defer update: '+unit)

def revision_ai_quiescent(root):
 revision_units_inactive(AI_REVISION_BOSS_UNITS+AI_REVISION_CLEAN_UNITS)
 hermes_quiescent(root)
 for name in ('advisor/advisor.sqlite3','fc-daily/daily.sqlite3'):
  database=rooted(root,'/var/lib/fs-business-ranges/'+name);no_target_link(database)
  if not database.is_file():raise ValueError('existing AI job database missing')
  with contextlib.closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
   if db.execute("SELECT count(*) FROM jobs WHERE state IN ('pending','running')").fetchone()[0]:raise ValueError('active/unknown old AI report; preserve history and reconcile original ID before update')

def guards(manifest,root):
 if manifest.get('scope') in (REVISION_UI_SCOPE,RECOVERY_SCOPE):
  for target in (RECOVERY_TARGETS if manifest.get('scope')==RECOVERY_SCOPE else REVISION_UI_TARGETS).values():
   path=rooted(root,target);no_target_link(path)
   for item in (path,*path.parents):
    if item.exists():
     info=item.stat()
     if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022:raise ValueError('unsafe navigation ownership/mode')
    if item==root:break
 if manifest.get('scope')==AI_REVISION_SCOPE:revision_ai_quiescent(root)
 if manifest.get('scope') in (HERMES_NIGHT_SCOPE,AI_REVISION_SCOPE):
  if rooted(root,'/etc/localtime').read_bytes()!=rooted(root,'/usr/share/zoneinfo/Asia/Shanghai').read_bytes():raise ValueError('server timezone must be Asia/Shanghai')
 if manifest.get('scope') in (HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE):hermes_quiescent(root)
 if manifest.get('scope') in (DAILY_SCOPE,ADVISOR_SCOPE,DEEP_SCOPE,HERMES_SCOPE,HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE):
  for target in (quality_targets(manifest) if manifest.get('scope') in (HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE) else AI_REVISION_TARGETS if manifest.get('scope')==AI_REVISION_SCOPE else HERMES_NIGHT_TARGETS if manifest.get('scope')==HERMES_NIGHT_SCOPE else HERMES_AUTO_TARGETS if manifest.get('scope')==HERMES_AUTO_SCOPE else HERMES_CONTINUE_TARGETS if manifest.get('scope')==HERMES_CONTINUE_SCOPE else HERMES_REPORT_TARGETS if manifest.get('scope')==HERMES_REPORT_SCOPE else HERMES_SECRET_TARGETS if manifest.get('scope')==HERMES_SECRET_SCOPE else HERMES_CAPABILITY_TARGETS if manifest.get('scope')==HERMES_CAPABILITY_SCOPE else HERMES_HISTORY_TARGETS if manifest.get('scope')==HERMES_HISTORY_SCOPE else HERMES_WORKER_TARGETS if manifest.get('scope')==HERMES_WORKER_SCOPE else HERMES_DIRECT_TARGETS if manifest.get('scope')==HERMES_DIRECT_SCOPE else HERMES_CAPACITY_TARGETS if manifest.get('scope')==HERMES_CAPACITY_SCOPE else HERMES_WIRE_TARGETS if manifest.get('scope')==HERMES_WIRE_SCOPE else HERMES_UPDATE_TARGETS if manifest.get('scope')==HERMES_UPDATE_SCOPE else HERMES_TARGETS if manifest.get('scope')==HERMES_SCOPE else DEEP_TARGETS if manifest.get('scope')==DEEP_SCOPE else ADVISOR_TARGETS if manifest.get('scope')==ADVISOR_SCOPE else DAILY_TARGETS).values():
   path=rooted(root,target);no_target_link(path)
   for item in (path,*path.parents):
    if item.exists():
     s=item.stat()
     if s.st_uid!=0 or not approved_daily_group(manifest,root,item,s) or s.st_mode&0o022:raise ValueError('unsafe daily source boundary')
    if item==root:break
 if manifest.get("scope")==DETAIL_SCOPE:
  for target in DETAIL_TARGETS.values():
   path=rooted(root,target);no_target_link(path)
   for item in (path,*path.parents):
    if item.exists():
     info=item.stat()
     if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022:raise ValueError("unsafe FC target boundary")
    if item==root:break
 if manifest.get('scope') in (DEMAND_SCOPE,BOUNDARY_SCOPE):
  from grant_dy import grant_all
  registry=rooted(root,'/etc/fs-query-api/clients.json')
  no_target_link(registry)
  for target in DEMAND_TARGETS.values():
   path=rooted(root,target);no_target_link(path)
   for item in (path,*path.parents):
    if item.exists():
     info=item.stat()
     if info.st_uid!=0 or info.st_gid!=0 or info.st_mode & 0o022:raise ValueError('unsafe demand target ownership/mode')
     if item.is_file() and info.st_nlink!=1:raise ValueError('unsafe demand target link count')
    if item==root:break

 if manifest.get('scope')==GAMES_SCOPE:
  actual=subprocess.check_output(['docker','image','inspect','-f','{{.Id}}','fc27-cloud-session:business-live-20261010'],universal_newlines=True).strip()
  if actual!=manifest.get('sessionCurrentImage'):raise ValueError('game session image drift')
  base=subprocess.check_output(['docker','image','inspect','-f','{{.Id}}','fc27-cloud-session:traffic-20261009-ec4c7ba41c3c'],universal_newlines=True).strip()
  if base!=manifest.get('sessionBaseImage'):raise ValueError('game session base image drift')
  for target in GAMES_TARGETS.values():
   path=rooted(root,target);no_target_link(path)
   for item in (path,*path.parents):
    if item.exists():
     info=item.stat()
     if info.st_uid!=0 or info.st_gid!=0 or info.st_mode & 0o022:raise ValueError('unsafe game target ownership/mode')
     if item.is_file() and info.st_nlink!=1:raise ValueError('unsafe game target link count')
 if manifest.get('scope') in (LIVE_SCOPE,CACHE_FIX_SCOPE):
  actual=subprocess.check_output(['docker','image','inspect','-f','{{.Id}}','fc27-cloud-session:traffic-20261009-ec4c7ba41c3c'],universal_newlines=True).strip()
  if actual!=manifest['sessionBaseImage']:raise ValueError('live session base drift')
  for target in LIVE_TARGETS.values():
   path=rooted(root,target);no_target_link(path)
   for item in (path,*path.parents):
    if item.exists():
     info=item.stat()
     if info.st_uid!=0 or info.st_gid!=0 or info.st_mode & 0o022:raise ValueError('unsafe live target ownership/mode')
     if item.is_file() and info.st_nlink!=1:raise ValueError('unsafe live target link count')

 if manifest.get('scope')==TRAFFIC_SCOPE:
  actual=subprocess.check_output(['docker','image','inspect','-f','{{.Id}}','fc27-cloud-session:1'],universal_newlines=True).strip()
  if actual!=manifest['sessionBaseImage']:raise ValueError('session base image drift')

 for unit,expected in manifest.get('runtimeRequired',{}).items():
  if not re.fullmatch(r'[A-Za-z0-9@_.-]+\.(service|timer)',unit) or unit=='mmoexp-taskboard.service':raise ValueError('invalid protected unit')
  r=subprocess.run(['systemctl','show',unit,'--no-pager']+[v for k in expected for v in ('-p',k)],stdout=subprocess.PIPE,check=True,universal_newlines=True)
  actual=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
  if actual!=expected:raise ValueError('protected unit changed: '+unit)
 for row in manifest['unchangedRequired']:
  if digest(rooted(root,row['path']))!=row['sha256']:raise ValueError('protected source drift: '+row['path'])
def retirement(root):
 if rooted(root,'/opt/dashboard-collect/publish_to_server.py').exists():raise ValueError('old publisher reappeared')
 for unit in ('dashboard-pipeline.service','dashboard-publish.service','dashboard-fallback.service'):
  path=rooted(root,'/etc/systemd/system/'+unit)
  if not path.is_symlink() or str(path.readlink())!='/dev/null':raise ValueError('old release service no longer masked: '+unit)
 for unit in ('dashboard-pipeline.timer','dashboard-fallback.timer'):
  r=subprocess.run(['systemctl','show',unit,'--no-pager','-p','UnitFileState','-p','ActiveState'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
  props=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
  if r.returncode or props.get('UnitFileState')!='disabled' or props.get('ActiveState')!='inactive':raise ValueError('old release timer state changed: '+unit)
@contextlib.contextmanager
def locks(root):
 import fcntl
 handles=[]
 try:
  for name in ('fs-navigation-release.lock','fs-dashboard-release.lock'):
   path=rooted(root,'/var/lock/'+name);path.parent.mkdir(parents=True,exist_ok=True)
   fd=os.open(str(path),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1:
    os.close(fd);raise ValueError('unsafe release lock ownership/type')
   f=os.fdopen(fd,'a+b');handles.append(f);fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  yield
 finally:
  for f in reversed(handles):f.close()
def capability_lifecycle(manifest):
 import types
 path=Path(__file__).with_name('capability_image_lifecycle.py');no_target_link(path)
 raw=path.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=manifest.get('imageLifecycleSha256'):raise ValueError('image lifecycle source changed')
 # Compile reviewed source directly; no unverified import/bytecode cache.
 module=types.ModuleType('_reviewed_capability_image_lifecycle')
 exec(compile(raw,str(path),'exec'),module.__dict__)
 return module

def capability_image_baseline(manifest):
 capability_lifecycle(manifest).baseline(manifest)

def capability_session_apply(manifest,backup,journal,root):
 capability_lifecycle(manifest).apply(manifest,backup,journal,root,atomic,journal_write,digest,no_target_link)

def capability_session_restore(backup,journal):
 capability_lifecycle(journal['manifest']).restore(backup,journal,journal_write)

def inspect(manifest,stage,root=Path('/')):
 files=validate(manifest,stage);guards(manifest,root);retirement(root)
 if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:capability_image_baseline(manifest)
 if manifest.get('scope')==DEMAND_SCOPE:
  from grant_dy import grant_all
  registry=json.loads(rooted(root,'/etc/fs-query-api/clients.json').read_text())
  candidate=json.loads((stage/'candidate/machine/clients.json').read_text())
  if grant_all(registry)!=candidate:raise ValueError('only DY projects may change; preserve credentials and lifecycle')
 for row in files:
  path=rooted(root,row['target']);no_target_link(path)
  if digest(path)!=row['beforeSha256']:raise ValueError('target baseline drift: '+row['target'])
 return dict(releaseReady=manifest.get('releaseReady') is True,staticFiles=len(files),sourceCAS='passed',protectedCAS='passed',oldPublisher='still retired',mutations=False)
def journal_write(backup,journal):atomic(backup/'journal.json',json.dumps(journal,indent=2).encode(),0o600)
def rollback_credentials(backup,journal,approved_sha):
 no_target_link(backup/'approved-manifest.json')
 payload=(backup/'approved-manifest.json').read_bytes()
 if not HASH.fullmatch(approved_sha or '') or hashlib.sha256(payload).hexdigest()!=approved_sha or journal['approvedManifestSha256']!=approved_sha:raise ValueError('wrong release approval SHA')
 manifest=json.loads(payload)
 if journal['manifest']!=manifest:raise ValueError('journal manifest differs from approved bytes')
 files=manifest['files']
 expected=expected_files(manifest)
 if manifest.get('schemaVersion')!=1 or {r['candidate'] for r in files}!=expected or len(files)!=len(expected):raise ValueError('rollback manifest scope differs')
 if len(journal['files'])!=len(files) or {r['candidate'] for r in journal['files']}!=expected:raise ValueError('rollback journal scope differs')
 approved={r['candidate']:r for r in files}
 for row in journal['files']:
  original=approved[row['candidate']]
  if any(row.get(k)!=v for k,v in original.items()) or row['target']!=target_for(row['candidate']):raise ValueError('rollback target differs from approved manifest')
  if not HASH.fullmatch(row['sha256']) or (row['beforeSha256'] is not None and not HASH.fullmatch(row['beforeSha256'])):raise ValueError('invalid rollback hash')
  if manifest.get('scope')==GREEN_FIX_SCOPE and row['beforeSha256'] is None:raise ValueError('review-fix rollback baseline required')

def rollback_journal(backup,journal,root):
 if journal['manifest'].get('scope')==HERMES_SCOPE:
  subprocess.run(['systemctl','stop','fs-hermes-fc.service'],check=True)
 rollback_credentials(backup,journal,journal['approvedManifestSha256'])
 if journal['manifest'].get('scope')==ACCOUNT_SCOPE:
  path=rooted(root,'/opt/auth-portal/data/registration-approval/registration.sqlite3');no_target_link(path)
  with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
   if db.execute('PRAGMA user_version').fetchone()[0]>=5:raise ValueError('account changes are active; pre-schema5 code rollback refused; preserve database/checkpoint/audit and use compatible forward repair')
 if journal['manifest'].get('scope')==PERMISSION_SCOPE:
  path=rooted(root,'/opt/auth-portal/data/registration-approval/registration.sqlite3');no_target_link(path)
  with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
   if db.execute('PRAGMA user_version').fetchone()[0]!=3 or db.execute("SELECT 1 FROM audit WHERE action='permissions' LIMIT 1").fetchone():
    raise ValueError('module permissions are active; legacy rollback refused, use schema4-compatible recovery; preserve database and checkpoint')
 rows=[]
 # Validate the entire release before restoring anything; unrelated runtime/files
 # are release preconditions, not permission to block restoring our exact code.
 for row in journal['files']:
  path=rooted(root,row['target']);no_target_link(path)
  sha=digest(path)
  if row.get('intent'):
   if sha not in (row['sha256'],row['beforeSha256']):raise ValueError('rollback intent target drift; preserve all files for manual review')
   if sha==row['sha256']:rows.append(row)
   elif row.get('written') and not row.get('rollbackIntent'):raise ValueError('rollback CAS drift; preserve for manual review: '+row['target'])
  elif row.get('written'):raise ValueError('written target lacks durable intent')
  if row['beforeSha256'] is not None:
   saved=backup/'files'/row['candidate'];no_target_link(saved)
   if digest(saved)!=row['beforeSha256']:raise ValueError('rollback backup SHA mismatch')
 for row in reversed(rows):
  path=rooted(root,row['target'])
  payload=None
  if row['beforeSha256'] is not None:
   payload=(backup/'files'/row['candidate']).read_bytes()
   if hashlib.sha256(payload).hexdigest()!=row['beforeSha256']:raise ValueError('rollback backup changed after validation')
  row['rollbackIntent']=True;journal_write(backup,journal)
  no_target_link(path)
  if digest(path)!=row['sha256']:raise ValueError('rollback target changed after validation')
  if payload is None:
   atomic(backup/'removed-new-files'/row['candidate'],path.read_bytes(),0o600)
   if digest(path)!=row['sha256']:raise ValueError('new file changed before removal')
   path.unlink();directory_sync(path.parent)
  else:atomic(path,payload,row['beforeMode'])
  row['written']=False;journal_write(backup,journal)
 if journal['manifest'].get('scope')==HERMES_CAPABILITY_SCOPE:capability_session_restore(backup,journal)
 journal['status']='rolled-back';journal_write(backup,journal)

def db_state(root):
 path=rooted(root,'/opt/mmoexp-taskboard/data/taskboard.db')
 with contextlib.closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as conn:
  names=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'green_%' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
  counts={name:conn.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in names}
  members=conn.execute('SELECT * FROM members ORDER BY username').fetchall()
  return dict(counts=counts,membersSha256=hashlib.sha256(json.dumps(members,ensure_ascii=False,default=str).encode()).hexdigest())
def restart_taskboard():
 subprocess.run(['systemctl','restart','mmoexp-taskboard.service'],check=True)
 subprocess.run(['systemctl','is-active','--quiet','mmoexp-taskboard.service'],check=True)
 for attempt in range(50):
  try:
   with urllib.request.urlopen('http://127.0.0.1:8932/health',timeout=1) as response:
    if response.status==200:return
  except OSError:pass
  time.sleep(0.1)
 raise ValueError('taskboard health unavailable after restart')
def restart_query():
 unit=Path('/etc/systemd/system/fs-query-api.service')
 if not unit.exists():
  subprocess.run(['systemctl','stop','fs-query-api.service'],check=False)
  subprocess.run(['systemctl','disable','fs-query-api.service'],check=False)
  subprocess.run(['systemctl','daemon-reload'],check=True)
 else:
  subprocess.run(['systemctl','daemon-reload'],check=True)
  subprocess.run(['nginx','-t'],check=True)
  subprocess.run(['systemctl','start','fs-query-api.service'],check=True)
  ready=False
  for attempt in range(50):
   try:
    with urllib.request.urlopen('http://127.0.0.1:8933/api/fs/v1/profiles',timeout=1):raise ValueError('anonymous API allowed')
   except urllib.error.HTTPError as error:
    if error.code!=401:raise ValueError('unexpected query service response')
    ready=True;break
   except OSError:time.sleep(0.1)
  if not ready:raise ValueError('query API unavailable')
  subprocess.run(['systemctl','enable','fs-query-api.service'],check=True)
 subprocess.run(['nginx','-t'],check=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)

def restart_traffic(manifest):
 source=Path('/opt/fc27-cloud/marketing-session-20261009')
 if (source/'Dockerfile.session').exists():
  subprocess.run(['docker','build','--network','none','--pull=false','-f',str(source/'Dockerfile.session'),'-t','fc27-cloud-session:traffic-20261009-ec4c7ba41c3c',str(source)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  output=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','sha256sum','fc27-cloud-session:traffic-20261009-ec4c7ba41c3c','/usr/local/bin/p2pah_session_service.py','/usr/local/bin/admin_links.py'],universal_newlines=True)
  expected={row['sha256'] for row in manifest['files'] if row['candidate'] in ('session/p2pah_session_service.py','session/admin_links.py')}
  if {line.split()[0] for line in output.splitlines()}!=expected:raise ValueError('built session source SHA differs')
 subprocess.run(['systemctl','daemon-reload'],check=True)
 for unit in ('auth-portal.service','fc27-p2pah-session.service'):
  subprocess.run(['systemctl','restart',unit],check=True)
  subprocess.run(['systemctl','is-active','--quiet',unit],check=True)
 if Path('/etc/systemd/system/fs-marketing-range.service').exists():
  subprocess.run(['systemctl','restart','fs-marketing-range.service'],check=True)
  subprocess.run(['systemctl','enable','fs-marketing-range.service'],check=True)
 else:
  subprocess.run(['systemctl','stop','fs-marketing-range.service'],check=False)
  subprocess.run(['systemctl','disable','fs-marketing-range.service'],check=False)
 for url,expected in [('http://127.0.0.1:8895/verify',401),('http://127.0.0.1:8767/health',200)]:
  ready=False
  for attempt in range(120):
   try:
    with urllib.request.urlopen(url,timeout=2) as response:code=response.status
   except urllib.error.HTTPError as error:code=error.code;error.close()
   except OSError:code=None
   if code==expected:ready=True;break
   time.sleep(1)
  if not ready:raise ValueError('existing service health failed after traffic release')

def restart_live(manifest):
 source=Path('/opt/fc27-cloud/marketing-session-20261009')
 installed=digest(source/'p2pah_session_service.py')
 candidate=next(r['sha256'] for r in manifest['files'] if r['candidate']=='session/p2pah_session_service.py')
 if installed==candidate:
  subprocess.run(['docker','build','--network','none','--pull=false','-f',str(source/'Dockerfile.session'),'-t','fc27-cloud-session:business-live-20261010',str(source)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  output=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','sha256sum','fc27-cloud-session:business-live-20261010','/usr/local/bin/p2pah_session_service.py','/usr/local/bin/admin_summary.py','/usr/local/bin/supplement_fields.py'],universal_newlines=True)
  expected={r['sha256'] for r in manifest['files'] if r['candidate'] in ('session/p2pah_session_service.py','session/admin_summary.py','session/supplement_fields.py')}
  if {line.split()[0] for line in output.splitlines()}!=expected:raise ValueError('live image bytes differ')
 subprocess.run(['systemctl','daemon-reload'],check=True)
 for unit in ('fc27-p2pah-session.service','fs-business-range.service'):
  subprocess.run(['systemctl','restart',unit],check=True)
  subprocess.run(['systemctl','is-active','--quiet',unit],check=True)
 for url in ('http://127.0.0.1:8767/health','http://127.0.0.1:8931/health'):
  ready=False
  for _ in range(90):
   try:
    with urllib.request.urlopen(url,timeout=2) as response:value=json.load(response)
    if value.get('ready') is True or value.get('status')=='ready' or value.get('ok') is True:ready=True;break
   except (OSError,ValueError):pass
   time.sleep(1)
  if not ready:raise ValueError('live health unavailable')

def restart_games(manifest):
 source=Path('/opt/fc27-cloud/marketing-session-20261009')
 protected={r['path']:r['sha256'] for r in manifest['unchangedRequired']}
 admin=next(r for r in manifest['files'] if r['candidate']=='games/admin_summary.py')
 expected={name:digest(source/name) for name in ('p2pah_session_service.py','admin_summary.py','supplement_fields.py')}
 if expected['admin_summary.py'] not in (admin['sha256'],admin['beforeSha256']):raise ValueError('game admin source drift')
 for name in ('p2pah_session_service.py','supplement_fields.py'):
  if expected[name]!=protected.get((source/name).as_posix()):raise ValueError('game protected session source drift')
 subprocess.run(['docker','build','--network','none','--pull=false','-f',str(source/'Dockerfile.session'),'-t','fc27-cloud-session:business-live-20261010',str(source)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 names=['p2pah_session_service.py','admin_summary.py','supplement_fields.py']
 output=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','sha256sum','fc27-cloud-session:business-live-20261010']+['/usr/local/bin/'+name for name in names],universal_newlines=True)
 actual={Path(line.split()[1]).name:line.split()[0] for line in output.splitlines()}
 if actual!=expected:raise ValueError('game session image bytes differ')
 for unit in ('fc27-p2pah-session.service','fs-business-range.service'):
  subprocess.run(['systemctl','restart',unit],check=True)
  subprocess.run(['systemctl','is-active','--quiet',unit],check=True)
 for url in ('http://127.0.0.1:8767/health','http://127.0.0.1:8931/health'):
  for _ in range(90):
   try:
    with urllib.request.urlopen(url,timeout=2) as response:value=json.load(response)
    if value.get('ready') is True or value.get('status')=='ready' or value.get('ok') is True:break
   except (OSError,ValueError):pass
   time.sleep(1)
  else:raise ValueError('game range/session health unavailable')

def restart_for(manifest,admission_fence=None):
 if manifest.get('scope') in (HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE):
  if admission_fence is None:raise ValueError('report quality admission fence required')
  admission_fence.stop_then_unlock_database()
  restart_for(dict(manifest,scope=HERMES_WORKER_SCOPE),admission_fence)
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return
 if manifest.get('scope')==AI_REVISION_SCOPE:
  if admission_fence is None:raise ValueError('AI revision requires Hermes admission fence')
  revision_ai_quiescent(admission_fence.root)
  subprocess.run(['systemctl','daemon-reload'],check=True)
  revision_units_inactive(AI_REVISION_CLEAN_UNITS)
  admission_fence.stop_then_unlock_database()
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return
 if manifest.get('scope')==HERMES_NIGHT_SCOPE:
  if admission_fence is None:raise ValueError('nightly admission fence required')
  subprocess.run(['systemctl','daemon-reload'],check=True)
  for unit in NIGHT_TIMERS:
   if Path('/var/lib/fs-hermes-fc/fs/nightly-schedule.json').is_file():
    subprocess.run(['systemctl','restart',unit],check=True)
    subprocess.run(['systemctl','is-active','--quiet',unit],check=True)
   else:subprocess.run(['systemctl','disable','--now',unit],check=True)
  admission_fence.stop_then_unlock_database()
  restart_for(dict(manifest,scope=HERMES_WORKER_SCOPE),admission_fence)
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return

 if manifest.get('scope')==HERMES_DESKTOP_SCOPE:
  if admission_fence is None:raise ValueError('desktop admission fence required')
  admission_fence.stop_then_unlock_database()
  subprocess.run(['systemctl','daemon-reload'],check=True)
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return

 if manifest.get('scope') in (HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE):
  if admission_fence is None:raise ValueError('Hermes admission fence required for report update')
  admission_fence.stop_then_unlock_database()
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return
 if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:
  if admission_fence is None:raise ValueError('capability admission fence required')
  admission_fence.stop_then_unlock_database()
  restart_for(dict(manifest,scope=HERMES_WORKER_SCOPE),admission_fence)
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return
 if manifest.get('scope') in (HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE):
  if admission_fence is None:raise ValueError('Hermes admission fence required for history update')
  admission_fence.stop_then_unlock_database()
  # Refresh registry parameter schema and FS adapters under the same file fence.
  restart_for(dict(manifest,scope=HERMES_WORKER_SCOPE),admission_fence)
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return
 if manifest.get('scope')==HERMES_WORKER_SCOPE:
  if admission_fence is None:raise ValueError('Hermes admission fence required for worker update')
  # FS stays up but rejects admission throughout the worker restart/readback.
  subprocess.run(['systemctl','restart','fs-hermes-fc.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','fs-hermes-fc.service'],check=True)
  key_path=rooted(admission_fence.root,'/run/fs-hermes-fc/api-key');no_target_link(key_path)
  key=key_path.read_text('ascii').strip()
  request=urllib.request.Request('http://127.0.0.1:8941/v1/capabilities',headers={'Authorization':'Bearer '+key})
  for attempt in range(50):
   try:
    with urllib.request.urlopen(request,timeout=1) as response:
     raw=response.read(128001)
     if len(raw)>128000 or not isinstance(json.loads(raw),dict):raise ValueError('Hermes capabilities contract')
     return
   except OSError:
    if attempt==49:raise ValueError('Hermes worker health failed')
    time.sleep(.1)
 if manifest.get('scope') in (HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_SECRET_SCOPE):
  if admission_fence is None:raise ValueError('Hermes admission fence required for update')
  admission_fence.stop_then_unlock_database()
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return
 if manifest.get('scope')==HERMES_SCOPE:
  subprocess.run(['systemctl','daemon-reload'],check=True)
  if Path('/etc/systemd/system/fs-hermes-fc.service').is_file():
   subprocess.run(['systemctl','restart','fs-hermes-fc.service'],check=True)
   subprocess.run(['systemctl','is-active','--quiet','fs-hermes-fc.service'],check=True)
  restart_for(dict(manifest,scope=DEEP_SCOPE))
  return
 if manifest.get('scope')==DEMAND_SCOPE:
  for name,port in [('fs-business-range.service',8931),('fs-query-api.service',8933)]:
   subprocess.run(['systemctl','restart',name],check=True)
   subprocess.run(['systemctl','is-active','--quiet',name],check=True)
   for attempt in range(50):
    try:
     path='/health' if port==8931 else '/api/fs/v1/profiles'
     with urllib.request.urlopen('http://127.0.0.1:'+str(port)+path,timeout=1) as response:
      if port==8931 and json.load(response).get('ok') is True:break
      raise ValueError('anonymous machine API must remain denied')
    except urllib.error.HTTPError as error:
     if port==8933 and error.code==401:break
     raise
    except OSError:
     if attempt==49:raise ValueError('on-demand consumer health failed')
     time.sleep(.1)
  return
 if manifest.get('scope')==GAMES_SCOPE:restart_games(manifest);return
 if manifest.get('scope') in (CACHE_FIX_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE,DAILY_SCOPE,ADVISOR_SCOPE,DEEP_SCOPE,HERMES_SCOPE,HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE):
  subprocess.run(['systemctl','restart','fs-business-range.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','fs-business-range.service'],check=True)
  for _ in range(50):
   try:
    with urllib.request.urlopen('http://127.0.0.1:8931/health',timeout=1) as response:
     if json.load(response).get('ok') is True:return
   except OSError:pass
   time.sleep(0.1)
  raise ValueError('range health failed')
 if manifest.get('scope') in (LIVE_SCOPE,CACHE_FIX_SCOPE):restart_live(manifest);return
 if manifest.get("scope")==TRAFFIC_SCOPE:restart_traffic(manifest);return
 if manifest.get("scope")==QUERY_SCOPE:restart_query();return
 if manifest.get('scope') in (GREEN_FIX_SCOPE,PERMISSION_SCOPE,ACCOUNT_SCOPE):
  subprocess.run(['systemctl','restart','auth-portal.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','auth-portal.service'],check=True)
  for attempt in range(50):
   try:
    with urllib.request.urlopen('http://127.0.0.1:8895/verify',timeout=1) as response:raise ValueError('anonymous auth verify unexpectedly allowed')
   except urllib.error.HTTPError as error:
    if error.code==401:break
    raise ValueError('anonymous auth verify must return 401') from error
   except OSError:
    if attempt==49:raise ValueError('auth verify unavailable after restart')
    time.sleep(0.1)
 if manifest.get('scope') in ('green-plan-20261009',GREEN_FIX_SCOPE,PERMISSION_SCOPE,ACCOUNT_SCOPE):restart_taskboard()

@contextlib.contextmanager
def live_lock(manifest,root):
 if manifest.get('scope') not in (LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE,DAILY_SCOPE,ADVISOR_SCOPE,DEEP_SCOPE,HERMES_SCOPE,HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE):
  yield;return
 import fcntl
 path=rooted(root,'/var/www/dashboard/fs-home/transactions/collector.lock')
 no_target_link(path)
 fd=os.open(str(path),os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1:raise ValueError('unsafe collector lock')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  yield
 finally:os.close(fd)

class HermesAdmissionFence:
 def __init__(self,root):
  import fcntl
  self.root=root;self.db=None;self.modified=False;self.confirmed=False
  path=rooted(root,'/var/lib/fs-hermes-fc/fs/admission.lock');no_target_link(path)
  self.fd=os.open(str(path),os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
  try:
   info=os.fstat(self.fd)
   if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid() or info.st_mode&0o077:raise ValueError('unsafe Hermes admission lock')
   fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   database=rooted(root,'/var/lib/fs-hermes-fc/fs/tasks.sqlite3');no_target_link(database)
   if not database.is_file():raise ValueError('existing Hermes task database required')
   self.db=sqlite3.connect('file:'+str(database)+'?mode=rw',uri=True,timeout=0)
   # This also fences the currently installed pre-lock controller. No row changes.
   self.db.execute('BEGIN IMMEDIATE')
   hermes_quiescent(root)
  except Exception:
   self.close();raise
 def unlock_database(self):
  if self.db is not None:self.db.rollback();self.db.close();self.db=None
 def stop_then_unlock_database(self):
  # Old admissions remain blocked until their process has stopped. The new
  # controller honors the file fence throughout startup and final readback.
  subprocess.run(['systemctl','stop','fs-business-range.service'],check=True)
  self.unlock_database()
 def close(self):
  self.unlock_database()
  if self.fd is not None:os.close(self.fd);self.fd=None

@contextlib.contextmanager
def hermes_admission_fence(manifest,root):
 if manifest.get('scope') not in (HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE):yield None;return
 fence=HermesAdmissionFence(root)
 try:yield fence
 finally:
  try:
   # Unconfirmed rollback must not reopen the old pre-lock admission path.
   if fence.modified and not fence.confirmed:fence.stop_then_unlock_database()
  finally:fence.close()

def hermes_quiescent(root):
 path=rooted(root,'/var/lib/fs-hermes-fc/fs/tasks.sqlite3');no_target_link(path)
 if not path.is_file():raise ValueError('existing Hermes task database required')
 with contextlib.closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)) as db:
  if db.execute("SELECT count(*) FROM requests WHERE state IN ('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE')").fetchone()[0]:
   raise ValueError('active or unreconciled Hermes task; defer update')

@contextlib.contextmanager
def model_release_lock(manifest,root):
 if manifest.get('scope') not in (DEEP_SCOPE,HERMES_SCOPE,HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE):
  yield;return
 import fcntl
 path=rooted(root,'/var/lib/fs-business-ranges/fc-daily/provider.lock');no_target_link(path)
 fd=os.open(str(path),os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1:raise ValueError('unsafe provider lock')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  # No restart of an active report. The shared provider lock also excludes sends during replacement.
  for name in ('advisor/advisor.sqlite3','fc-daily/daily.sqlite3'):
   database=rooted(root,'/var/lib/fs-business-ranges/'+name);no_target_link(database)
   if not database.is_file():raise ValueError('existing job database missing')
   with contextlib.closing(sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)) as db:
    if db.execute("SELECT count(*) FROM jobs WHERE state IN ('pending','running')").fetchone()[0]:raise ValueError('active report; defer restart')
  if manifest.get('scope') in (HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE):hermes_quiescent(root)
  yield
 finally:os.close(fd)

@contextlib.contextmanager
def account_snapshot(root):
 import fcntl
 path=rooted(root,'/opt/auth-portal/data/registration-approval/namespace.lock');no_target_link(path)
 fd=os.open(path,os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or info.st_mode&0o077:raise ValueError('unsafe account namespace lock')
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  yield
 finally:os.close(fd)

def apply(manifest,stage,approved_sha,manifest_bytes,release_id,root=Path('/')):
 if manifest.get('releaseReady') is not True:raise ValueError('releaseReady=false; permission/real-role gate remains OPEN')
 if hashlib.sha256(manifest_bytes).hexdigest()!=approved_sha:raise ValueError('reviewed manifest approval SHA differs')
 if not re.fullmatch(r'nav-[0-9]{8}T[0-9]{6}Z',release_id):raise ValueError('release id must be nav-YYYYMMDDTHHMMSSZ')
 files=validate(manifest,stage)
 with locks(root),live_lock(manifest,root),hermes_admission_fence(manifest,root) as admission_fence,model_release_lock(manifest,root):
  inspect(manifest,stage,root)
  backup=rooted(root,'/var/backups/fs-navigation-20261006/'+release_id)
  if backup.exists():raise ValueError('release id already used; do not retry blindly')
  no_target_link(backup)
  backup.mkdir(parents=True,mode=0o700);directory_sync(backup.parent)
  journal=dict(status='prepared',approvedManifestSha256=approved_sha,manifest=manifest,files=[])
  if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:journal['sessionImageBefore']=manifest['sessionCurrentImage']
  for row in files:
   path=rooted(root,row['target'])
   saved={**row,'beforeMode':stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600 if row['candidate']=='hermes/nightly/nightly-schedule.json' else 0o644,'written':False}
   if path.exists():atomic(backup/'files'/row['candidate'],path.read_bytes(),0o600)
   if saved['beforeSha256'] is not None and digest(backup/'files'/row['candidate'])!=saved['beforeSha256']:raise ValueError('backup source drift')
   journal['files'].append(saved)
  atomic(backup/'approved-manifest.json',manifest_bytes,0o600);journal_write(backup,journal)
  green=manifest.get('scope') in ('green-plan-20261009',GREEN_FIX_SCOPE,PERMISSION_SCOPE,ACCOUNT_SCOPE)
  if green:
   journal['databaseBefore']=db_state(root)
   source=rooted(root,'/opt/mmoexp-taskboard/data/taskboard.db')
   saved=backup/'taskboard-private.sqlite3'
   with contextlib.closing(sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True)) as src, contextlib.closing(sqlite3.connect(str(saved))) as dst:src.backup(dst)
   os.chmod(saved,0o600);journal_write(backup,journal)
  if manifest.get('scope')==ACCOUNT_SCOPE:
   with account_snapshot(root):
    source=rooted(root,'/opt/auth-portal/data/registration-approval/registration.sqlite3');no_target_link(source)
    with contextlib.closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, contextlib.closing(sqlite3.connect(str(backup/'registration-private.sqlite3'))) as dst:src.backup(dst)
    os.chmod(backup/'registration-private.sqlite3',0o600)
    witness=rooted(root,'/opt/auth-portal/data/.registration-checkpoint/state.json');no_target_link(witness)
    atomic(backup/'registration-checkpoint-private.json',witness.read_bytes(),0o600)
  ordered=sorted(journal['files'],key=lambda row:(row['candidate']=='fs-home/index.html',row['candidate']=='hubnav.js',row['candidate']))
  try:
   for row in ordered:
    guards(manifest,root);retirement(root)
    path=rooted(root,row['target']);no_target_link(path)
    if digest(path)!=row['beforeSha256']:raise ValueError('target drift before replacement: '+row['target'])
    payload=(stage/'candidate'/row['candidate']).read_bytes()
    if hashlib.sha256(payload).hexdigest()!=row['sha256']:raise ValueError('staged source changed during release')
    # Journal intent before rename; recovery can classify old/new hashes after a crash.
    row['intent']=True;journal_write(backup,journal)
    if admission_fence is not None:admission_fence.modified=True
    atomic(path,payload,row['beforeMode']);row['written']=True;journal_write(backup,journal)
   guards(manifest,root);retirement(root)
   if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:capability_session_apply(manifest,backup,journal,root)
   if manifest.get('scope') in (QUERY_SCOPE,TRAFFIC_SCOPE,LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE,DAILY_SCOPE,ADVISOR_SCOPE,DEEP_SCOPE,HERMES_SCOPE,HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE):restart_for(manifest,admission_fence)
   if green:
    restart_for(manifest,admission_fence)
    journal['databaseAfter']=db_state(root)
    if journal['databaseAfter']!=journal['databaseBefore']:raise ValueError('Existing database tables/members changed during initialization')
   if any(digest(rooted(root,row['target']))!=row['sha256'] for row in journal['files']):raise ValueError('post-release SHA mismatch')
   journal['status']='applied-awaiting-actual-http-role-acceptance';journal_write(backup,journal)
   if admission_fence is not None:admission_fence.confirmed=True
  except Exception as error:
   # The rename may have succeeded before a later fsync/journal error.
   for row in journal['files']:
    if row.get('intent') and digest(rooted(root,row['target']))==row['sha256']:row['written']=True
   journal['failure']=str(error)
   try:journal_write(backup,journal)
   except OSError:pass
   rollback_journal(backup,journal,root)
   if green or manifest.get('scope') in (QUERY_SCOPE,TRAFFIC_SCOPE,LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE,DAILY_SCOPE,ADVISOR_SCOPE,DEEP_SCOPE,HERMES_SCOPE,HERMES_SECRET_SCOPE,HERMES_UPDATE_SCOPE,HERMES_DESKTOP_SCOPE,HERMES_DIRECT_SCOPE,HERMES_CAPACITY_SCOPE,HERMES_WIRE_SCOPE,HERMES_WORKER_SCOPE,HERMES_HISTORY_SCOPE,HERMES_REPORT_SCOPE,HERMES_QUALITY_SCOPE,HERMES_PROOF_SCOPE,HERMES_CONTINUE_SCOPE,HERMES_AUTO_SCOPE,HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE):restart_for(manifest,admission_fence)
   if admission_fence is not None:admission_fence.confirmed=True
   raise
  return dict(backup=str(backup),status=journal['status'],staticFiles=len(files),businessWorkerTimerActions=0)
def rollback(backup,approved_sha,root=Path('/')):
 with locks(root):
  no_target_link(backup/'journal.json')
  journal=json.loads((backup/'journal.json').read_text())
  rollback_credentials(backup,journal,approved_sha)
  with live_lock(journal['manifest'],root),hermes_admission_fence(journal['manifest'],root) as admission_fence,model_release_lock(journal['manifest'],root):
   if admission_fence is not None:admission_fence.modified=True
   rollback_journal(backup,journal,root)
   restart_for(journal['manifest'],admission_fence)
   if admission_fence is not None:admission_fence.confirmed=True
 return dict(status='rolled-back',backup=str(backup),businessWorkerTimerActions=0)

def retire_collection(manifest,raw,approval,release_id,root=Path('/')):
 if manifest.get('schemaVersion')!=1 or manifest.get('scope')!='fs-on-demand-retire-20261012' or manifest.get('releaseReady') is not True or hashlib.sha256(raw).hexdigest()!=approval:raise ValueError('approved retirement manifest required')
 required={'catalogue','frontend','dailyProfit','weeklyCurrent','weeklyPrevious','machine17','sevenGames','anonymousDenied'}
 if set(manifest.get('acceptance',{}))!=required or any(v is not True for v in manifest['acceptance'].values()):raise ValueError('all actual consumer acceptance required before retirement')
 paths={r['path'] for r in manifest['unchangedRequired']}
 if not set(DEMAND_TARGETS.values()).issubset(paths) or not {'/var/www/dashboard/fs-home/index.html','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf','/etc/systemd/system/fs-transaction-collect.timer'}.issubset(paths):raise ValueError('exact deployed consumer and timer hashes required')
 if manifest.get('runtimeRequired',{}).get('fs-transaction-collect.service')!={'ActiveState':'inactive'}:raise ValueError('collector must be inactive')
 if not re.fullmatch(r'nav-[0-9]{8}T[0-9]{6}Z',release_id):raise ValueError('fixed release id required')
 backup=rooted(root,'/var/backups/fs-navigation-20261006/'+release_id)
 with locks(root),live_lock({'scope':DEMAND_SCOPE},root):
  if backup.exists():raise ValueError('retirement id already used; reconcile its journal')
  guards(manifest,root);retirement(root)
  timer='fs-transaction-collect.timer'
  before=subprocess.check_output(['systemctl','show',timer,'-p','UnitFileState','-p','ActiveState'],universal_newlines=True)
  if dict(line.split('=',1) for line in before.splitlines() if '=' in line)!={'UnitFileState':'enabled','ActiveState':'active'}:raise ValueError('unexpected timer state; preserve and reconcile')
  backup.mkdir(parents=True,mode=0o700);directory_sync(backup.parent)
  atomic(backup/'approved-manifest.json',raw,0o600)
  journal={'status':'prepared','approvedManifestSha256':approval,'manifest':manifest,'timerBefore':before,'timerIntent':False}
  journal_write(backup,journal);guards(manifest,root)
  journal['timerIntent']=True;journal_write(backup,journal)
  try:
   subprocess.run(['systemctl','disable','--now',timer],check=True)
   after=subprocess.check_output(['systemctl','show',timer,'-p','UnitFileState','-p','ActiveState'],universal_newlines=True)
   journal['timerAfter']=after
   if dict(line.split('=',1) for line in after.splitlines() if '=' in line)!={'UnitFileState':'disabled','ActiveState':'inactive'}:raise ValueError('timer stop readback differs')
   guards(manifest,root);journal['status']='retired'
  except Exception:
   journal['status']='retirement-outcome-needs-reconciliation';journal_write(backup,journal);raise
  journal_write(backup,journal)
 return {'status':'retired','timer':timer,'backup':str(backup),'snapshotsDeleted':0,'otherTimerActions':0}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','apply','rollback','retire'],nargs='?',default='inspect');parser.add_argument('--manifest',type=Path,default=Path(__file__).parent/'approved-manifest.json');parser.add_argument('--approved-manifest-sha');parser.add_argument('--release-id');parser.add_argument('--backup',type=Path)
 args=parser.parse_args()
 if args.action!='inspect' and os.name!='posix':raise ValueError('mutating commands require reviewed Linux release environment')
 if args.action=='rollback':
  if not args.backup or args.backup.parent!=Path('/var/backups/fs-navigation-20261006'):raise ValueError('backup must be exactly one navigation release backup')
  result=rollback(args.backup,args.approved_manifest_sha)
 else:
  manifest_bytes=args.manifest.read_bytes();manifest=json.loads(manifest_bytes)
  result=retire_collection(manifest,manifest_bytes,args.approved_manifest_sha,args.release_id) if args.action=='retire' else inspect(manifest,args.manifest.parent) if args.action=='inspect' else apply(manifest,args.manifest.parent,args.approved_manifest_sha,manifest_bytes,args.release_id)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
