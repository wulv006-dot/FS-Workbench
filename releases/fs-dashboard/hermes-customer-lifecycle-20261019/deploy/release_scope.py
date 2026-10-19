SCOPE='customer-pool-lifecycle-20261019'
TARGETS={f'source/{n}.py':f'/opt/fs-hermes-fc/{n}.py' for n in ['customer_tracking','tracking_controller','tracking_tool','pool_reports']}
TARGETS.update({'source/page.js':'/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/page.js','source/index.html':'/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/index.html'})
NEW_ALLOWED={'/opt/fs-hermes-fc/pool_reports.py'}
APPLICATION_SCHEDULE={'customer_history':'daily 00:00-07:00 Asia/Shanghai','customer_reports':'manual active pool only; per-customer auto reports retired','timezone':'Asia/Shanghai','existingFCJobs':'unchanged','systemdTimersChanged':False}
