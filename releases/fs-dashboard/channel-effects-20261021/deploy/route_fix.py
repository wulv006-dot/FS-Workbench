"""Single-route correction using the original locked CAS/backup/rollback engine."""
import release

SCOPE = 'fs-channel-route-20261021'
TARGETS = {'generated/navigation.conf':'/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', 'runtime/channel_effects.py':'/opt/fs-hermes-fc/channel_effects.py'}


def candidate(before):
    anchor = b'location = /dashboard/channel-effects/ {\n    if ($request_method !~ ^(GET|HEAD)$)'
    ending = b'\r\n' if anchor.replace(b'\n',b'\r\n') in before else b'\n'
    anchor = anchor.replace(b'\n',ending)
    fixed = b'location = /dashboard/channel-effects/ {\n    rewrite ^ /dashboard/channel-effects/index.html last;\n}\nlocation = /dashboard/channel-effects/index.html {\n    if ($request_method !~ ^(GET|HEAD)$)'.replace(b'\n',ending)
    if before.count(anchor) != 1: raise ValueError('exact_channel_directory_route_required')
    return before.replace(anchor, fixed, 1)


def load_base():
    release.SCOPE, release.TARGETS, release.NEW = SCOPE, TARGETS, frozenset()
    return release.load_base()


if __name__ == '__main__': load_base().main()
