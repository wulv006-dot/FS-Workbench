"""Exact material-files adapter over the original publisher, not a new writer."""
from contextlib import closing, nullcontext
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import types

HERE = Path(__file__).resolve().parent
SCOPE = 'hermes-materials-runtime-20261101'
BASE_SHA = '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
FROZEN_IMAGE_MARKER = 'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
NGINX = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
TARGETS = {'runtime/' + name: '/opt/fs-hermes-fc/' + name for name in (
    'conversation_store.py', 'conversation_files.py', 'conversation_file_bindings.py',
    'conversation_service.py', 'conversation_file_tools.py', 'material_evidence.py',
    'runs_contract.py', 'proxy_gateway.py', 'hermes_worker.py')}
TARGETS.update({'http/conversation_http.py': '/opt/fs-exact-range-20261001/conversation_http.py',
                'http/formal.conf': NGINX})
TARGETS.update({'frontend/' + name: '/var/www/dashboard/fs-home/hermes/conversation/' + name
                for name in ('index.html', 'conversation.js', 'conversation.css')})
NEW = frozenset('runtime/' + name for name in (
    'conversation_files.py', 'conversation_file_bindings.py',
    'conversation_file_tools.py', 'material_evidence.py'))
INSTALLED_COMMIT = '1f8ddc57c37e16df7c802de358eefb6585d078ee'
INSTALLED_PROOF = {
    'sourceCommit': INSTALLED_COMMIT,
    'backup': '/var/backups/fs-navigation-20261006/nav-20261031T192312Z',
    'manifestSha256': 'b129179049dc9ff4b575075ebd1b47c1f6edf325936ac70b1286ca990bd73a05',
    'journalSha256': 'c902e8f3d1d613c80f1f0573647dbcf17184466579fdfbc77539d8f8846c24fc'}
INSTALLED_NGINX_SHA = 'b792f18b8d1b322139f8be96bb5052ff53a79e82dac7a607cbe102e199b06302'
LEGACY_TARGETS = dict(TARGETS)
EXECUTION_MODE = False
DIAGNOSTICS_MODE = False
TASK_INDEX_MODE = False
WORKER_DIAGNOSTICS_MODE = False
TRANSPORT_MODE = False
STREAM_MODE = False
BINDINGS_MODE = False
GUARD_MODE = False
NATIVE_MODE = False
NATIVE_ADMISSION_MODE = False
ARCHIVE_MODE = False
NATIVE_CAPABILITIES_MODE = False
COMPOSER_STATIC_MODE = False
COMPOSER_STATIC_METADATA = {}
COMPOSER_STATIC_PROOF = dict(sourceCommit='20c481384fcd746ccb6b122c7fe57f3d6185c51f',
    backup='/var/backups/fs-navigation-20261006/nav-20261103T011909Z',
    manifestSha256='2f2cfcb5fac5aa9dc2ae910f25eb0ad83fa0c91e72f331cc9fe6f559593497e6',
    journalSha256='fe028bc753ec6f5a387fe4675a4a4b5ec395fd898cda9f3bb304f1829e256298')
COMPOSER_BEFORE_SHA = '395c192a691c85a0d5787be8cd476afe08e9cc5135354f9ce46022bc95b35279'
COMPOSER_AFTER_SHA = '6254b7ce313c52b48402e47b881400086cd69decdcfca50932b2b8d4b7336ef8'
ARCHIVE_PROTECTED = {}
ARCHIVE_USAGE_LEDGER = '/var/lib/fs-hermes-fc/profile/skills/.usage.json'
ARCHIVE_NATIVE_PROOF = dict(backup='/var/backups/fs-navigation-20261006/nav-20261102T100758Z',
    manifestSha256='642d78db24159c3c79f04ca3f67f4e8cda2abdbcd5680022ba6c9e9f71969084',
    journalSha256='34f8e7a3dea5df8f05baf73d9e9bc668a3127444f8915f323cc15dce5e361266')
ARCHIVE_FC_PROOF = dict(sourceCommit='6d395242b88ca634c5745181e16f1fec6053c065',
    backup='/var/backups/fs-navigation-20261006/nav-20261102T175000Z',
    manifestSha256='900233dade3ab9a3922a8365345cffebbd8bdfd3cbe9a006081d5d1a6c91ab5a',
    journalSha256='5186d93010605186ec81d40e065758252d6cb8c93534edb27c753d11803afefc')
# PR765 raw Git bytes; build_stage copies the same sources.py to hermes-copy.
ARCHIVE_FC_FILES = {
    'source/fc_pricing_v3/sources.py':('/opt/fc27-cloud-browser/fc_pricing_v3/sources.py','449a53558c6607449abf1b070a11eff20aca58e689e0169331c28c24540ae635'),
    'source/hermes-copy/fc_pricing_v3/sources.py':('/opt/fs-hermes-fc/fc_pricing_v3/sources.py','449a53558c6607449abf1b070a11eff20aca58e689e0169331c28c24540ae635'),
    'source/server_quote_job.py':('/opt/fc27-cloud-browser/server_quote_job.py','139bd6d239330bad4770148188d31f2fcbdd0e31bc1f668e4056f0489debbee9')}
NATIVE_CAPABILITIES_PROOF = dict(sourceCommit='3c45f02689cab4e1b70a3fe1227031f833e17b02',
    backup='/var/backups/fs-navigation-20261006/nav-20261103T065027Z',
    manifestSha256='11fd2c4c2384913e7da9855028b50be05c3fc50836e658b5863fda3681c64eac',
    journalSha256='c946e8cac39b1f0fde71a05f9dea49d86f9c76173a5d9e2dd767c712fc4819bf')
CAPABILITIES_STATIC_PROOF = dict(sourceCommit='d135d2b965ecdfc2d96a1e49cf9425e31eaca07e',
    backup='/var/backups/fs-navigation-20261006/nav-20261103T021812Z',
    manifestSha256='26b0de09b7b84d9d7634948c3177ca7cf919bac6ea4aab00c247bd6389e8cbb8',
    journalSha256='e6dea978a851e0ac7017a7f06822c38574f3c0d754e70f7a9720ec0513dc972d')
CAPABILITIES_NGINX_PROOF = dict(
    backup='/var/backups/fs-navigation-native-20261006/workspace-native-20261006-07c816ca3c25',
    manifestSha256='0df40939921c58fda8a089a5b37d6d49e1629f2dc46153690047dd217fbed171',
    journalSha256='fa2355f41815a06633e6755388848d4864a901514e505fcb1c8a2336d28e95aa',
    beforeSha256='75a9b57a7073771b105573ab59e4c0a227f8567a75c8accbde2991d171934b3d',
    sha256='fde65e277cbb873673b7dc474483dada42e0da558756c69c63c38d0acc769da4',
    pageSha256='46a9d8f52a733f17a588c96940a2e8d1c7a0c831ae20d95799166f192cf26bb0')
CAPABILITIES_CHANGED = ('runtime/proxy_gateway.py',)
CAPABILITIES_STORE_BEFORE_SHA = 'ffa3a03e567fcef5bdd503a9673ce425584eb9b248227b2102ee44108a6914bf'
CAPABILITIES_TARGETS = {'runtime/'+name:'/opt/fs-hermes-fc/'+name for name in (
    'conversation_store.py','conversation_native.py','conversation_service.py','hermes_worker.py',
    'native_chat.py','transport.py','direct_provider.py','proxy_gateway.py','fs_inprocess.py')}
CAPABILITIES_TARGETS['http/conversation_http.py']='/opt/fs-exact-range-20261001/conversation_http.py'
CAPABILITIES_INSTALLED_TARGETS=dict(CAPABILITIES_TARGETS)
CAPABILITIES_NEW=frozenset()
CAPABILITIES_TARGETS.update({'runtime/'+name:'/opt/fs-hermes-fc/'+name for name in
    ('b2_customer_followup.py','user_runtime.py','conversation_user_data.py','a2_query_context.py','live_order_consumer.py','fs_native_readonly.py')})
NATIVE_ADMISSION_CANDIDATE = 'runtime/conversation_native.py'
NATIVE_ADMISSION_BEFORE_SHA = '030e36d5cf134fa1ef63c576211a3f1b4f2d9a3135ed44c15a7fd1d403e795c2'
NATIVE_ADMISSION_AFTER_SHA = '72253b5ffee19cc2d0352c0bb1ee7d67fe801fcb515b3b711466e828a4c1a57a'
NATIVE_CURRENT_UNIT_SHA = '5f31448a6396d8d702d2cda1df7d192cd022e7d42f53d04a2a97e1664e9955e3'
NATIVE_SOCKET_GID = 994
NATIVE_UNIT = '/etc/systemd/system/fs-hermes-fc.service.d/install-state-isolation.conf'
NATIVE_UNIT_BEFORE_SHA = '2a4eeada8c0acd27db04aa14838af7cc5c7fe3355677581d53f1f3509c74321a'
NATIVE_PROVIDER_BEFORE_SHA = '91d301ebe3578d0e6c60c23252510ebb34416a57f9f5dfc4ffd744f5ae0c74fa'
NATIVE_CLI = '/usr/bin/docker'
NATIVE_CLI_SHA = 'bfc304d1c5d8694b5c9bacc1c52c2f8d50e65b6f3e29446283a2561e23667be7'
NATIVE_ROOT = '/var/lib/fs-hermes-fc/native'
NATIVE_EMPTY_SOURCE = '/var/lib/fs-hermes-fc/native-backend-home'
NATIVE_LEGACY_DAILY = '/var/lib/fs-hermes-fc/profile/scripts/hermes-memory-review/daily_review.py'
NATIVE_LEGACY_DAILY_SHA = '33c77c007b97061e13e7f530d4e550b25151b6ed11b3fcdf1c878da0bbe56c0d'
NATIVE_DAILY_CONTAINER = '/profile/scripts/hermes-memory-review/daily_review.py'
NATIVE_EXTRA_TARGETS = {
    'runtime/direct_provider.py':'/opt/fs-hermes-fc/direct_provider.py',
    'runtime/conversation_native.py':'/opt/fs-hermes-fc/conversation_native.py',
    'runtime/native_chat.py':'/opt/fs-hermes-fc/native_chat.py',
    'runtime/native-backend.json':'/opt/fs-hermes-fc/native-backend.json',
    'unit/native-control.conf':NATIVE_UNIT,
    'approval/review_queue.py':'/opt/fs-hermes-memory-approval/review_queue.py',
    'approval/native_review.py':'/opt/fs-hermes-memory-approval/native_review.py',
    'approval/reviewed_skills.py':'/opt/fs-hermes-memory-approval/reviewed_skills.py',
    'approval/daily_review.py':'/opt/fs-hermes-memory-approval/daily_review.py'}
NATIVE_EXTERNAL_BEFORE = {
    'approval/review_queue.py':'05ee9dc2e7c936504284bdbdf91343230594365741997a4f3fbdf6c65167387c',
    'approval/reviewed_skills.py':'a3d546177396ba906f66c4f8411111aaefb3c96371dc628ac5ada2daf023e660'}
NATIVE_INSTALLED_TARGETS = {}
NATIVE_INSTALLED_PROTECTED = frozenset()
NATIVE_ALLOWED = frozenset(NATIVE_EXTRA_TARGETS) | frozenset({
    'runtime/conversation_service.py','runtime/conversation_store.py','runtime/conversation_files.py',
    'runtime/conversation_file_bindings.py','runtime/hermes_worker.py','runtime/transport.py',
    'runtime/proxy_gateway.py','runtime/fs_inprocess.py','http/conversation_http.py','http/range_api.py',
    'frontend/index.html','frontend/conversation.css','frontend/conversation.js'})
GUARD_BEFORE_SHA = "a71849b7e5e8f3c5b55967c21d5383e2ff6afa7c7c5e3c6772dc0c80209ba945"
BINDINGS_CANDIDATE = "runtime/conversation_file_bindings.py"
BINDINGS_BEFORE_SHA = "655625ff698981c295539663d60ac54f21ebe2c1935dfef4f7a1dd3a27899294"
BINDINGS_TRANSPORT_SHA = "e682d8659812cf5b3a9cc44f3011a7f3de0a204c830855cbff2a85e1573c3052"
TRANSPORT_CANDIDATE = 'runtime/transport.py'
TRANSPORT_TARGET = '/opt/fs-hermes-fc/transport.py'
TRANSPORT_BEFORE_SHA = 'e677a186a893c346379ba572576afdfbd412612cc5c63146751182558743f843'
STREAM_BEFORE_SHA = '2ef021e7b3bc3efd76632cf1924b538860da5422a08a4a751d2a932ff6f1a23d'
EXECUTION_MODULES = ('conversation_goals.py','conversation_goal_tasks.py','conversation_material_runs.py',
                     'material_execution.py','b2_goal_state.py','b2_goal_host.py','b1_model_routing.py','b2_customer_followup.py')


def configure_execution():
    """Same publisher, explicit 501f installed-baseline increment; never a replay."""
    global INSTALLED_COMMIT, NEW, EXECUTION_MODE
    if EXECUTION_MODE:
        return
    EXECUTION_MODE = True
    INSTALLED_COMMIT = '501f90bf16fe114e70fcb05833cb1b2cf478e54c'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261031T201743Z',
        manifestSha256='6c6c1aceda92eba62cb694f112dc6df93f97dd05fc157c778b51c4ffe8daf920',
        journalSha256='9131be81c7c95da5c15a0c6ba49107102517952f009046e524dd813c1732c9b9')
    TARGETS.update({'runtime/'+name:'/opt/fs-hermes-fc/'+name for name in EXECUTION_MODULES})
    TARGETS.update({'runtime/fs_inprocess.py':'/opt/fs-hermes-fc/fs_inprocess.py',
                    'http/range_api.py':'/opt/fs-exact-range-20261001/range_api.py'})
    NEW = frozenset('runtime/'+name for name in EXECUTION_MODULES)


def configure_diagnostics():
    """Exact 5f99 follow-up: all 24 targets already exist, including NEW8."""
    global INSTALLED_COMMIT, NEW, DIAGNOSTICS_MODE
    if DIAGNOSTICS_MODE:
        return
    configure_execution()
    DIAGNOSTICS_MODE = True
    INSTALLED_COMMIT = '5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261101T013519Z',
        manifestSha256='4057435dce473622c5ef2f88ba0d55255a9f7b588a6e193f70a41cffca409881',
        journalSha256='3f6d474d37716610de334f14b9b7a699f879aae170471c065f5007c47e3ab93d')
    NEW = frozenset()


def configure_task_index_compat():
    """One host module over the exact installed f79 diagnostics release."""
    global INSTALLED_COMMIT, DIAGNOSTICS_MODE, TASK_INDEX_MODE
    if TASK_INDEX_MODE:
        return
    configure_diagnostics()
    DIAGNOSTICS_MODE, TASK_INDEX_MODE = False, True
    INSTALLED_COMMIT = 'f79e29f0d5921b103a218c5e6ed967a754858b9c'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261101T024500Z',
        manifestSha256='25cd452cfb25790502cab7a7561187f04da5af6e2096baf9a71fabb11ad199ee',
        journalSha256='534a813b17ea54422131403075156ec82fa2696959c575211e29cee3c0c6cdab')


def configure_worker_diagnostics():
    """Only the worker wrapper over the exact successful 1b20 installation."""
    global INSTALLED_COMMIT, TASK_INDEX_MODE, WORKER_DIAGNOSTICS_MODE
    if WORKER_DIAGNOSTICS_MODE:
        return
    configure_task_index_compat()
    TASK_INDEX_MODE, WORKER_DIAGNOSTICS_MODE = False, True
    INSTALLED_COMMIT = '1b20b91f2e7e023d90a0197053916ba9a59978e6'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261101T062133Z',
        manifestSha256='16615694e66cda7dcfffa4ba55381d21071b51cf45b3597be303f5ba2af4f235',
        journalSha256='912511fd8fc877d9155ca6fec30ec8bdf9ff5bd94b94d6443d4f764e529c2446')


def configure_material_transport():
    """Promote only the installed transport from the exact 82edf protection set."""
    global INSTALLED_COMMIT, WORKER_DIAGNOSTICS_MODE, TRANSPORT_MODE
    if TRANSPORT_MODE:
        return
    configure_worker_diagnostics()
    WORKER_DIAGNOSTICS_MODE, TRANSPORT_MODE = False, True
    INSTALLED_COMMIT = '82edf03573c3fed796d7a7ed2784134c5dd1f7ec'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261101T110803Z',
        manifestSha256='a9be5243f473129379e6662854be5236d9c69f08d86f97693d66039be86d5656',
        journalSha256='46b6f0f1258fb190330544ae0b1538504f0024457d0b2b7336999c42dc3bce67')
    TARGETS[TRANSPORT_CANDIDATE] = TRANSPORT_TARGET


def configure_material_stream():
    """One existing transport delta over the exact successful b362 installation."""
    global INSTALLED_COMMIT, TRANSPORT_MODE, STREAM_MODE
    if STREAM_MODE:
        return
    configure_material_transport()  # Target composition only; no 24->25 proof promotion.
    TRANSPORT_MODE, STREAM_MODE = False, True
    INSTALLED_COMMIT = 'b362bd3bfb3fc4eca4bcf1d47cb3f0550c8c6c04'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261101T123702Z',
        manifestSha256='02d2d4623467aaf62f617775a7c47084b6005cf26e8da150025d12be7a052833',
        journalSha256='92b65d1a2d17a8d979b5b1011002c35ff1b80997e51b3e7e8db01cc43699a82d')



def configure_bindings_auth():
    """One existing bindings delta over the successful 9edb stream installation."""
    global INSTALLED_COMMIT, STREAM_MODE, BINDINGS_MODE
    if BINDINGS_MODE:
        return
    configure_material_stream()
    STREAM_MODE, BINDINGS_MODE = False, True
    INSTALLED_COMMIT = '9edb8827c0bc21fce4173030bd09b7388b19c866'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261101T175040Z',
        manifestSha256='74270ff2d91e195a8279572ba48aaa35a4189a75597bceaa9496a4fbe9116088',
        journalSha256='831ca7e02476aa50ef9fb25c2b3cc52c28ad562979fff26a938992746a6fc3e7')

def configure_material_guard():
    """Existing transport only over the exact successful 8e2a guard install."""
    global INSTALLED_COMMIT, BINDINGS_MODE, GUARD_MODE
    if GUARD_MODE:
        return
    configure_bindings_auth()
    BINDINGS_MODE, GUARD_MODE = False, True
    INSTALLED_COMMIT = '8e2a456631fc5aa916c1366d087b9adbccb02f91'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261102T002030Z',
        manifestSha256='e3a949b35d55aac5048f22094d81bc9f7db7e4f684f7463a83044371f5d4d3a4',
        journalSha256='fc33024f58bb1222e288e6ab1374be16b543f93756f135833238b29be9e22c74')


def configure_native_chat():
    global INSTALLED_COMMIT, NEW, NATIVE_MODE, GUARD_MODE, NATIVE_INSTALLED_TARGETS, NATIVE_INSTALLED_PROTECTED
    if NATIVE_MODE:
        return
    configure_material_guard()
    NATIVE_INSTALLED_TARGETS = dict(TARGETS)
    NATIVE_INSTALLED_PROTECTED = frozenset(protected_paths(frozen()))
    NATIVE_MODE, GUARD_MODE = True, False
    INSTALLED_COMMIT = '23a27325b00f27a5c5696657c7c4141a06135f18'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261102T010331Z',
        manifestSha256='ae010cb6b11a1a7c7c4ed877ae7534dbfc63b443143955cdd990ed96dfe19cf4',
        journalSha256='d59396365261e5669b8a1ec4fc9432beea103ca23ed8f664b81b0a6de1fd3431')
    TARGETS.update(NATIVE_EXTRA_TARGETS)
    NEW = frozenset({'runtime/conversation_native.py','runtime/native_chat.py',
                     'runtime/native-backend.json','approval/native_review.py','approval/daily_review.py'})


def configure_native_admission():
    """Existing 34-file native installation; only host admission bytes may change."""
    global INSTALLED_COMMIT, NEW, NATIVE_ADMISSION_MODE
    if NATIVE_ADMISSION_MODE:
        return
    configure_native_chat()  # Composition only; bootstrap proof/NEW are replaced.
    NATIVE_ADMISSION_MODE = True
    NEW = frozenset()
    INSTALLED_COMMIT = '89e5db08edba36cf3d88efdb37601ee1ca53bc38'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261102T100758Z',
        manifestSha256='642d78db24159c3c79f04ca3f67f4e8cda2abdbcd5680022ba6c9e9f71969084',
        journalSha256='34f8e7a3dea5df8f05baf73d9e9bc668a3127444f8915f323cc15dce5e361266')


def configure_native_archive():
    global ARCHIVE_MODE, NATIVE_MODE, NATIVE_ADMISSION_MODE, INSTALLED_COMMIT, NEW
    if ARCHIVE_MODE:return
    configure_native_admission()
    ARCHIVE_MODE=True;NATIVE_MODE=False;NATIVE_ADMISSION_MODE=False
    keep={'runtime/conversation_store.py','runtime/conversation_native.py','runtime/conversation_service.py'}
    for key in list(TARGETS):
        if key not in keep:del TARGETS[key]
    NEW=frozenset()
    INSTALLED_COMMIT='89e5db08edba36cf3d88efdb37601ee1ca53bc38'
    INSTALLED_PROOF.update(sourceCommit='943c9f9317af20a7281ac773d0a4573f729a8dd5',
        backup='/var/backups/fs-navigation-20261006/nav-20261102T150526Z',
        manifestSha256='68e907842a53f744e77a6eb30b7c4b4d207ce922ae6a827542835accd8e3079e',
        journalSha256='340c44f080cd8edb96df0b012e66fa67b634ce5a2f49367292ae7838bc9cdfc9')


def configure_native_capabilities():
    """Customer scope contract over the accepted installed user-data relay."""
    global NATIVE_CAPABILITIES_MODE, INSTALLED_COMMIT, NEW
    if NATIVE_CAPABILITIES_MODE:return
    configure_native_archive()
    NATIVE_CAPABILITIES_MODE=True
    INSTALLED_COMMIT=NATIVE_CAPABILITIES_PROOF['sourceCommit']
    INSTALLED_PROOF.update(NATIVE_CAPABILITIES_PROOF)
    TARGETS.clear();TARGETS.update(CAPABILITIES_TARGETS)
    NEW=CAPABILITIES_NEW


def configure_native_composer_static():
    """One existing HTML over the accepted 20c installation; no runtime marker."""
    global COMPOSER_STATIC_MODE, INSTALLED_COMMIT, NEW
    if COMPOSER_STATIC_MODE:return
    if EXECUTION_MODE or ARCHIVE_MODE or NATIVE_MODE:
        raise ValueError('conflicting_material_followup_modes')
    COMPOSER_STATIC_MODE=True
    INSTALLED_COMMIT=COMPOSER_STATIC_PROOF['sourceCommit']
    INSTALLED_PROOF.update(COMPOSER_STATIC_PROOF)
    TARGETS.clear();TARGETS['frontend/index.html']='/var/www/dashboard/fs-home/hermes/conversation/index.html'
    NEW=frozenset()


def archive_store_module(source,expected_sha):
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha:raise ValueError('archive_store_source_drift')
    module=types.ModuleType('reviewed_archive_store');module.__file__=str(source)
    exec(compile(raw,str(source),'exec'),module.__dict__)
    return module


def archive_check(base,root,source,source_sha):
    """Use the reviewed Store's exact CAS with a read-only connection, no init."""
    from contextlib import contextmanager
    module=archive_store_module(source,source_sha)
    store=module.ConversationStore.__new__(module.ConversationStore)
    path=base.rooted(root,'/var/lib/fs-hermes-fc/fs/conversations/conversations.db')
    base.no_target_link(path)
    store.path=path
    @contextmanager
    def db():
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as connection:
            connection.row_factory=sqlite3.Row;connection.execute('PRAGMA query_only=ON')
            yield connection
    store.db=db
    with db() as connection:
        row=connection.execute('SELECT owner FROM conversations WHERE id=?',(module.SYNTHETIC_ARCHIVE['cid'],)).fetchone()
        if row is None:raise ValueError('archive_owner_binding_missing')
        owner=row['owner']
    return store.archive_synthetic_unknown(owner,_check_only=True)


def native_backend_bytes():
    return json.dumps({'version':'native_docker_v1','root':NATIVE_ROOT,
        'image':FROZEN_IMAGE_MARKER,'docker_binary':'/opt/fs-native-bin/docker',
        'docker_sha256':NATIVE_CLI_SHA,'uid':9876,'gid':9876},sort_keys=True).encode()


def promoted_transport_sha(manifest, base):
    paths = [row['path'] for row in manifest['unchangedRequired']]
    rows = [row for row in manifest['unchangedRequired'] if row['path'] == TRANSPORT_TARGET]
    if (len(paths) != len(set(paths)) or set(paths) != protected_paths(base) | {TRANSPORT_TARGET}
            or len(rows) != 1 or rows[0]['sha256'] != TRANSPORT_BEFORE_SHA):
        raise ValueError('exact_installed_transport_protection_required')
    return rows[0]['sha256']


def archive_fc_baseline(base, root, values):
    """Overlay only the three independently installed FC files, never disk drift."""
    records={}
    for name,key in (('approved-manifest.json','manifestSha256'),('journal.json','journalSha256')):
        path=base.rooted(root,ARCHIVE_FC_PROOF['backup']+'/'+name);base.no_target_link(path);info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or
                (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(0,0,0o600)):
            raise ValueError('archive_fc_proof_boundary_drift')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=ARCHIVE_FC_PROOF[key]:raise ValueError('archive_fc_proof_drift')
        records[name]=json.loads(raw)
    manifest,journal=records['approved-manifest.json'],records['journal.json']
    rows=manifest.get('files',[]);written=journal.get('files',[])
    if (manifest.get('sourceCommit')!=ARCHIVE_FC_PROOF['sourceCommit'] or
            manifest.get('scope')!='fc-pricing-v3-collection-routing-20261102' or len(rows)!=3 or
            {r['candidate']:(r['target'],r['sha256']) for r in rows}!=ARCHIVE_FC_FILES or
            journal.get('manifest')!=manifest or journal.get('approvedManifestSha256')!=ARCHIVE_FC_PROOF['manifestSha256'] or
            journal.get('status')!='applied-awaiting-actual-http-role-acceptance' or journal.get('failure') or
            len(written)!=3 or {r['candidate'] for r in written}!=set(ARCHIVE_FC_FILES)):
        raise ValueError('archive_fc_successful_proof_required')
    for row in rows:
        target=row['target'];matches=[r for r in written if r['candidate']==row['candidate']]
        if (target not in values or target in TARGETS.values() or row.get('beforeSha256')!=values[target] or
                row.get('owner')!='0:0' or row.get('mode')!='0o644' or len(matches)!=1 or
                any(matches[0].get(k)!=v for k,v in row.items()) or
                matches[0].get('intent') is not True or matches[0].get('written') is not True or
                matches[0].get('beforeMode')!=0o644 or matches[0].get('rollbackIntent') or matches[0].get('rolledBack')):
            raise ValueError('archive_fc_exact_transition_required')
        path=base.rooted(root,target);base.no_target_link(path);info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or
                (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(0,0,0o644)):
            raise ValueError('archive_fc_target_boundary_drift')
    return dict(values,**{r['target']:r['sha256'] for r in rows})


def capabilities_static_overlay(base, root, metadata):
    """Accept only the already successful single-HTML transition, not disk drift."""
    records={}
    for name,key in (('approved-manifest.json','manifestSha256'),('journal.json','journalSha256')):
        path=base.rooted(root,CAPABILITIES_STATIC_PROOF['backup']+'/'+name)
        base.no_target_link(path);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=CAPABILITIES_STATIC_PROOF[key]:
            raise ValueError('native_static_successful_proof_drift')
        records[name]=json.loads(raw)
    manifest,journal=records['approved-manifest.json'],records['journal.json']
    html='/var/www/dashboard/fs-home/hermes/conversation/index.html'
    rows=manifest.get('files',[]);protected=manifest.get('unchangedRequired',[]);written=journal.get('files',[])
    if (manifest.get('sourceCommit')!=CAPABILITIES_STATIC_PROOF['sourceCommit'] or manifest.get('scope')!=SCOPE or
            manifest.get('nativeComposerStatic') is not True or manifest.get('materialStaticOnly') is not True or
            any(manifest.get(k) for k in ('nativeCapabilities','nativeArchive','nativeChat','materialExecution')) or
            len(rows)!=1 or len(written)!=1 or len(protected)!=778 or
            len({r['path'] for r in protected})!=778 or {r['path'] for r in protected}!=set(metadata)-{html} or
            any(rows[0].get(k)!=v for k,v in dict(candidate='frontend/index.html',target=html,
                beforeSha256=COMPOSER_BEFORE_SHA,sha256=COMPOSER_AFTER_SHA,owner='0:0',mode='0o644').items()) or
            metadata[html]['sha256']!=COMPOSER_BEFORE_SHA or
            journal.get('status')!='applied-awaiting-actual-http-role-acceptance' or journal.get('failure') or
            journal.get('manifest')!=manifest or journal.get('approvedManifestSha256')!=CAPABILITIES_STATIC_PROOF['manifestSha256'] or
            any(written[0].get(k)!=rows[0].get(k) for k in ('candidate','target','beforeSha256','sha256','owner','mode')) or
            written[0].get('intent') is not True or written[0].get('written') is not True or
            written[0].get('rollbackIntent') or written[0].get('rolledBack')):
        raise ValueError('native_static_exact_success_required')
    for row in protected:
        before=metadata[row['path']]
        keys=('owner','mode') if row['path']==ARCHIVE_USAGE_LEDGER else ('sha256','owner','mode')
        if any(row.get(k)!=before.get(k) for k in keys):
            raise ValueError('native_static_protected_chain_drift')
    return dict(metadata,**{html:dict(path=html,sha256=COMPOSER_AFTER_SHA,owner='0:0',mode='0o644')})


def capabilities_nginx_overlay(base, root, metadata):
    """Validate current protected SHA and its original transition; change neither."""
    if not NATIVE_CAPABILITIES_MODE:raise ValueError('native_nginx_capabilities_only')
    proof=CAPABILITIES_NGINX_PROOF;old=metadata.get(NGINX,{})
    if (NGINX in TARGETS.values() or any(old.get(k)!=v for k,v in
            dict(path=NGINX,sha256=proof['sha256'],owner='0:0',mode='0o600').items())):
        raise ValueError('native_nginx_transition_baseline_drift')
    records={}
    for name,key in (('approved-manifest.json','manifestSha256'),('journal.json','journalSha256')):
        path=base.rooted(root,proof['backup']+'/'+name);base.no_target_link(path);before=path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or
                (before.st_uid,before.st_gid,stat.S_IMODE(before.st_mode))!=(0,0,0o600)):
            raise ValueError('native_nginx_proof_boundary_drift')
        with os.fdopen(os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)),'rb') as stream:
            opened=os.fstat(stream.fileno())
            if any(getattr(before,k)!=getattr(opened,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_nlink')):
                raise ValueError('native_nginx_proof_changed')
            raw=stream.read()
        after=path.lstat();base.no_target_link(path)
        if any(getattr(before,k)!=getattr(after,k) for k in
               ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink','st_uid','st_gid','st_mode')):
            raise ValueError('native_nginx_proof_changed')
        if hashlib.sha256(raw).hexdigest()!=proof[key]:raise ValueError('native_nginx_proof_drift')
        records[name]=json.loads(raw)
    manifest,journal=records['approved-manifest.json'],records['journal.json'];name=Path(proof['backup']).name
    expected=dict(target=NGINX,candidate='candidate/formal.conf',beforeSha256=proof['beforeSha256'],sha256=proof['sha256'])
    select=lambda rows:[r for r in rows if r.get('target')==NGINX or r.get('candidate')==expected['candidate']]
    rows=select(manifest.get('targets',[]));written=select(journal.get('files',[]))
    page=dict(candidate='assets/game-monitor/index.html',target='/var/lib/fs-navigation-formal-static/'+name+'/game-monitor/index.html',sha256=proof['pageSha256'])
    pages=[r for r in manifest.get('immutableAssets',[]) if r.get('target')==page['target'] or r.get('candidate')==page['candidate']]
    if (manifest.get('releaseId')!=name or manifest.get('releaseReady') is not True or
            manifest.get('scope')!='Hermes authorized data-only game-monitor content maintenance' or
            journal.get('status')!='applied-awaiting-real-desktop-URL-QA' or journal.get('activationAttempted') is not True or
            journal.get('manifest')!=manifest or journal.get('approvedManifestSha256')!=proof['manifestSha256'] or
            journal.get('failure') or any(journal.get(k) for k in ('rollback','rollbackIntent','rolledBack','rollbackAttempted')) or
            any(r.get(k) for r in journal.get('files',[]) for k in ('rollbackIntent','rolledBack','rollbackWritten')) or
            len(rows)!=1 or len(written)!=1 or len(pages)!=1 or
            any(rows[0].get(k)!=v or written[0].get(k)!=v for k,v in expected.items()) or
            written[0].get('intent') is not True or written[0].get('mode')!=0o600 or
            any(pages[0].get(k)!=v for k,v in page.items())):
        raise ValueError('native_nginx_exact_success_required')
    # Native schema records intent + a successful final-SHA check, not written
    # or sourceCommit. Do not synthesize them or import its other protected rows.
    return dict(metadata)


def installed_baseline(root, git_baseline):
    """Bind an installed baseline to both the successful journal and Git bytes."""
    base = frozen()
    records = {}
    for name, key in (('approved-manifest.json', 'manifestSha256'), ('journal.json', 'journalSha256')):
        path = base.rooted(root, INSTALLED_PROOF['backup'] + '/' + name)
        base.no_target_link(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != INSTALLED_PROOF[key]:
            raise ValueError('installed_release_proof_drift')
        records[name] = json.loads(raw)
    manifest, journal = records['approved-manifest.json'], records['journal.json']
    global ARCHIVE_PROTECTED
    if COMPOSER_STATIC_MODE or NATIVE_CAPABILITIES_MODE:
        rows=manifest.get('files',[]);protected=manifest.get('unchangedRequired',[])
        metadata={r['target']:{'path':r['target'],'sha256':r['sha256'],'owner':r.get('owner'),'mode':r.get('mode')} for r in rows}
        metadata.update({r['path']:dict(r) for r in protected})
        written=journal.get('files',[])
        installed_targets=CAPABILITIES_TARGETS if NATIVE_CAPABILITIES_MODE else CAPABILITIES_INSTALLED_TARGETS
        if (manifest.get('sourceCommit')!=INSTALLED_COMMIT or manifest.get('scope')!=SCOPE or
                manifest.get('nativeCapabilities') is not True or manifest.get('nativeArchive') is not True or
                len(rows)!=len(installed_targets) or {r['candidate']:r['target'] for r in rows}!=installed_targets or
                len(protected)!=(767 if NATIVE_CAPABILITIES_MODE else 769) or len(metadata)!=(783 if NATIVE_CAPABILITIES_MODE else 779) or
                journal.get('status')!='applied-awaiting-actual-http-role-acceptance' or journal.get('failure') or
                journal.get('manifest')!=manifest or journal.get('approvedManifestSha256')!=INSTALLED_PROOF['manifestSha256'] or
                len(written)!=len(installed_targets) or {r['candidate'] for r in written}!=set(installed_targets) or
                any(any(w.get(k)!=r.get(k) for k in ('candidate','target','beforeSha256','sha256','owner','mode')) or
                    w.get('intent') is not True or w.get('written') is not True or w.get('rollbackIntent') or w.get('rolledBack')
                    for r in rows for w in written if r['candidate']==w['candidate']) or
                metadata.get('/var/www/dashboard/fs-home/hermes/conversation/index.html',{}).get('sha256')!=(COMPOSER_AFTER_SHA if NATIVE_CAPABILITIES_MODE else COMPOSER_BEFORE_SHA) or
                NATIVE_CAPABILITIES_MODE and manifest.get('nativeStaticBaseline')!=CAPABILITIES_STATIC_PROOF or
                git_baseline!={'source_commit':INSTALLED_COMMIT,'files':(
                    {'frontend/index.html':COMPOSER_BEFORE_SHA} if COMPOSER_STATIC_MODE else
                    {name:None if name in NEW else metadata.get(target,{}).get('sha256') for name,target in TARGETS.items()})}):
            raise ValueError('composer_static_installed_proof_mismatch')
        if NATIVE_CAPABILITIES_MODE:metadata=capabilities_nginx_overlay(base,root,metadata)
        COMPOSER_STATIC_METADATA.clear()
        COMPOSER_STATIC_METADATA.update({p:r for p,r in metadata.items() if p not in TARGETS.values()})
        ARCHIVE_PROTECTED={p:r['sha256'] for p,r in COMPOSER_STATIC_METADATA.items()}
        all_hashes={p:r['sha256'] for p,r in metadata.items()}
        all_hashes.update({TARGETS[name]:None for name in NEW})
        return dict(manifest,archive_all_hashes=all_hashes)
    if ARCHIVE_MODE:
        rows=manifest.get('files',[]);protected=manifest.get('unchangedRequired',[])
        values={r['target']:r['sha256'] for r in rows}
        values.update({r['path']:r['sha256'] for r in protected})
        if (manifest.get('sourceCommit')!=INSTALLED_PROOF['sourceCommit'] or
                manifest.get('scope')!='user-admin-live-page-20261102' or len(rows)!=8 or len(protected)!=743 or len(values)!=751 or
                journal.get('status')!='applied-awaiting-actual-http-role-acceptance' or
                journal.get('approvedManifestSha256')!=INSTALLED_PROOF['manifestSha256'] or journal.get('manifest')!=manifest):
            raise ValueError('archive_live_installed_proof_mismatch')
        backup=ARCHIVE_NATIVE_PROOF['backup']
        original={}
        for name,sha in (('approved-manifest.json',ARCHIVE_NATIVE_PROOF['manifestSha256']),('journal.json',ARCHIVE_NATIVE_PROOF['journalSha256'])):
            path=base.rooted(root,backup+'/'+name);base.no_target_link(path);raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('archive_native_installed_proof_drift')
            original[name]=json.loads(raw)
        old=original['approved-manifest.json'];old_journal=original['journal.json']
        if (old.get('sourceCommit')!=INSTALLED_COMMIT or len(old.get('files',[]))!=34 or len(old.get('unchangedRequired',[]))!=45 or
                old_journal.get('manifest')!=old or old_journal.get('status')!='applied-awaiting-actual-http-role-acceptance'):
            raise ValueError('archive_native_installed_proof_mismatch')
        merged={r['target']:r['sha256'] for r in old['files']};merged.update({r['path']:r['sha256'] for r in old['unchangedRequired']})
        updated={r['target'] for r in rows}
        if any(path in merged and merged[path]!=sha and path not in updated for path,sha in values.items()):
            raise ValueError('archive_protected_chain_conflict')
        merged.update(values);values=archive_fc_baseline(base,root,merged)
        if git_baseline!={'source_commit':INSTALLED_COMMIT,'files':{name:values.get(target) for name,target in TARGETS.items()}}:
            raise ValueError('archive_installed_git_mismatch')
        ARCHIVE_PROTECTED={path:sha for path,sha in values.items() if path not in TARGETS.values()}
        return dict(manifest,archive_all_hashes=values)
    if NATIVE_ADMISSION_MODE:
        expected = {row['candidate']:row['sha256'] for row in manifest['files']}
        protected = manifest.get('unchangedRequired', [])
        if (manifest.get('sourceCommit') != INSTALLED_COMMIT or manifest.get('scope') != SCOPE or
                manifest.get('nativeChat') is not True or manifest.get('nativeAdmission') or
                len(manifest['files']) != len(TARGETS) or
                {row['candidate']:row['target'] for row in manifest['files']} != TARGETS or
                any(row.get('owner') != '0:0' or row.get('mode') != ('0o600' if row['target'] == NGINX else '0o644') for row in manifest['files']) or
                len(protected) != len(protected_paths(base)) or
                {row['path'] for row in protected} != protected_paths(base) or
                expected.get(NATIVE_ADMISSION_CANDIDATE) != NATIVE_ADMISSION_BEFORE_SHA or
                expected.get('unit/native-control.conf') != NATIVE_CURRENT_UNIT_SHA or
                expected.get('runtime/native-backend.json') != hashlib.sha256(native_backend_bytes()).hexdigest() or
                journal.get('status') != 'applied-awaiting-actual-http-role-acceptance' or
                journal.get('approvedManifestSha256') != INSTALLED_PROOF['manifestSha256'] or
                journal.get('manifest') != manifest or
                git_baseline != {'source_commit':INSTALLED_COMMIT,'files':expected,
                    'protected':{NATIVE_LEGACY_DAILY:NATIVE_LEGACY_DAILY_SHA}}):
            raise ValueError('native_admission_installed_git_and_journal_mismatch')
        return manifest
    if NATIVE_MODE:
        expected = {row['candidate']:row['sha256'] for row in manifest['files']}
        expected.update({name:None for name in NEW})
        expected.update(NATIVE_EXTERNAL_BEFORE)
        expected['unit/native-control.conf'] = NATIVE_UNIT_BEFORE_SHA
        expected['runtime/direct_provider.py'] = NATIVE_PROVIDER_BEFORE_SHA
        protected = manifest.get('unchangedRequired', [])
        if (manifest.get('sourceCommit') != INSTALLED_COMMIT or manifest.get('scope') != SCOPE or
                len(manifest['files']) != len(NATIVE_INSTALLED_TARGETS) or
                {row['candidate']:row['target'] for row in manifest['files']} != NATIVE_INSTALLED_TARGETS or
                len(protected) != len(NATIVE_INSTALLED_PROTECTED) or
                {row['path'] for row in protected} != NATIVE_INSTALLED_PROTECTED or
                next((row['sha256'] for row in protected if row['path'] == NATIVE_UNIT),None) != NATIVE_UNIT_BEFORE_SHA or
                next((row['sha256'] for row in protected if row['path'] == TARGETS['runtime/direct_provider.py']),None) != NATIVE_PROVIDER_BEFORE_SHA or
                journal.get('status') != 'applied-awaiting-actual-http-role-acceptance' or
                journal.get('approvedManifestSha256') != INSTALLED_PROOF['manifestSha256'] or
                journal.get('manifest') != manifest or git_baseline != {'source_commit':INSTALLED_COMMIT,'files':expected,
                    'protected':{NATIVE_LEGACY_DAILY:NATIVE_LEGACY_DAILY_SHA}}):
            raise ValueError('native_installed_git_and_journal_mismatch')
        return manifest
    expected = {row['candidate']: row['sha256'] for row in manifest['files']}
    proof_targets = LEGACY_TARGETS if EXECUTION_MODE and not (DIAGNOSTICS_MODE or TASK_INDEX_MODE or WORKER_DIAGNOSTICS_MODE or TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE) else TARGETS
    if BINDINGS_MODE and (len(manifest['files']) != len(TARGETS)
            or expected.get(BINDINGS_CANDIDATE) != BINDINGS_BEFORE_SHA
            or expected.get(TRANSPORT_CANDIDATE) != BINDINGS_TRANSPORT_SHA
            or len(manifest['unchangedRequired']) != len(protected_paths(base))
            or {row['path'] for row in manifest['unchangedRequired']} != protected_paths(base)):
        raise ValueError('exact_installed_bindings_targets_required')
    if (STREAM_MODE or GUARD_MODE) and (len(manifest['files']) != len(TARGETS)
            or expected.get(TRANSPORT_CANDIDATE) != (GUARD_BEFORE_SHA if GUARD_MODE else STREAM_BEFORE_SHA)
            or len(manifest['unchangedRequired']) != len(protected_paths(base))
            or {row['path'] for row in manifest['unchangedRequired']} != protected_paths(base)):
        raise ValueError('exact_installed_guard_targets_required' if GUARD_MODE else 'exact_installed_stream_targets_required')
    if TRANSPORT_MODE:
        proof_targets = {name: path for name, path in TARGETS.items() if name != TRANSPORT_CANDIDATE}
        expected[TRANSPORT_CANDIDATE] = promoted_transport_sha(manifest, base)
        if len(manifest['files']) != len(proof_targets):
            raise ValueError('exact_installed_transport_targets_required')
    if EXECUTION_MODE and not (DIAGNOSTICS_MODE or TASK_INDEX_MODE or WORKER_DIAGNOSTICS_MODE or TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE):
        protected = {r['path']:r['sha256'] for r in manifest['unchangedRequired']}
        expected.update({name: None if name in NEW else protected[target]
                         for name,target in TARGETS.items() if name not in LEGACY_TARGETS})
    if (manifest.get('sourceCommit') != INSTALLED_COMMIT or manifest.get('scope') != SCOPE
            or {row['candidate']: row['target'] for row in manifest['files']} != proof_targets
            or journal.get('status') != 'applied-awaiting-actual-http-role-acceptance'
            or journal.get('approvedManifestSha256') != INSTALLED_PROOF['manifestSha256']
            or journal.get('manifest') != manifest
            or git_baseline != {'source_commit': INSTALLED_COMMIT, 'files': expected}):
        raise ValueError('installed_git_and_journal_mismatch')
    return manifest


def frozen():
    raw = (HERE / 'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('frozen_publisher_drift')
    source = raw.decode('utf-8')
    anchor = "r.get('beforeSha256') is None for r in files if not ("
    if source.count(anchor) != 1:
        raise ValueError('frozen_new_file_anchor_drift')
    source = source.replace(anchor, "r.get('beforeSha256') is None for r in files if r['candidate'] not in MATERIAL_NEW if not (", 1)
    base = types.ModuleType('original_material_publisher')
    base.__file__ = str(HERE / 'release_navigation_base.py')
    base.MATERIAL_NEW = NEW
    exec(compile(source, base.__file__, 'exec'), base.__dict__)
    base.HERMES_HISTORY_SCOPE, base.HERMES_HISTORY_TARGETS = SCOPE, TARGETS
    base.expected_files = lambda manifest: set(TARGETS) if manifest.get('scope') == SCOPE else set()
    base.target_for = lambda name: TARGETS[name]
    return base


def protected_paths(base):
    if COMPOSER_STATIC_MODE:return set(COMPOSER_STATIC_METADATA)
    if ARCHIVE_MODE:return set(ARCHIVE_PROTECTED)
    # Preserve the original publisher's required consumers, plus this package's
    # unchanged live host/seams. No DB, credential or model-key payload is copied.
    paths = set(base.HERMES_TARGETS.values()) | {
        '/opt/fs-exact-range-20261001/' + name for name in (
            'boss_insights.py', 'fc_deep_model.py', 'fc_daily.py', 'fc_daily_model.py',
            'fc_detail.py', 'fc_detail_model.py', 'fc_detail_reader.py',
            'fc_detail_config.json', 'fc_deep_sources.py', 'summary_bridge.py')}
    paths.update(('/var/www/dashboard/index.html', '/var/www/dashboard/fs-home/index.html',
                  '/var/www/dashboard/fs-home/navigation.js', '/opt/fs-access-policy/access_policy.py',
                  '/opt/fs-hermes-fc/direct_provider.py', '/etc/systemd/system/fs-business-range.service',
                  '/etc/systemd/system/fs-hermes-fc.service.d/install-state-isolation.conf'))
    if NATIVE_MODE:
        paths.add(NATIVE_CLI)
        paths.add(NATIVE_LEGACY_DAILY)
    return paths - set(TARGETS.values())


def worker_observation(*, allow_stopped=False):
    checked = subprocess.run(['docker', 'inspect', '--format', '{{.Image}}', 'fs-hermes-fc'],
                             capture_output=True, text=True, timeout=10)
    if checked.returncode:
        # The original unit uses --rm and Restart=no: a failed worker may have
        # no container. Only pre-install checks can use its exact installed unit
        # and locally present pinned image; post-restart still requires a container.
        if (not allow_stopped or checked.returncode != 1
                or checked.stderr.strip() != 'Error: No such object: fs-hermes-fc'):
            raise ValueError('current_worker_container_unavailable')
        def output(command):
            return subprocess.check_output(command, universal_newlines=True, timeout=10).strip()
        if output(['docker', 'ps', '-a', '--filter', 'name=^/fs-hermes-fc$', '--format', '{{.ID}}']):
            raise ValueError('worker_container_changed_during_observation')
        unit = '/etc/systemd/system/fs-hermes-fc.service'
        dropin = unit + '.d/install-state-isolation.conf'
        expected = {unit: '94b9cf19547ad0a4b68307ea35d4f5317fca0136048b90d78d5f9cea1dbaf011',
                    dropin: '2a4eeada8c0acd27db04aa14838af7cc5c7fe3355677581d53f1f3509c74321a'}
        base = frozen()
        for name, sha in expected.items():
            path = Path(name)
            base.no_target_link(path)
            info = path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (info.st_uid, info.st_gid) != (0, 0)
                    or stat.S_IMODE(info.st_mode) & 0o022
                    or hashlib.sha256(path.read_bytes()).hexdigest() != sha):
                raise ValueError('stopped_worker_unit_drift')
        state = dict(line.split('=', 1) for line in output([
            'systemctl', 'show', 'fs-hermes-fc.service', '-p', 'ActiveState',
            '-p', 'FragmentPath', '-p', 'DropInPaths', '-p', 'NeedDaemonReload']).splitlines())
        if (state.get('ActiveState') not in ('failed', 'inactive')
                or state.get('FragmentPath') != unit or state.get('DropInPaths') != dropin
                or state.get('NeedDaemonReload') != 'no'):
            raise ValueError('stopped_worker_unit_state_changed')
        # Both exact unit bytes above pin this image; do not resolve mutable tags
        # or substitute another image when recovery is needed.
        value = output(['docker', 'image', 'inspect', '--format', '{{.Id}}', FROZEN_IMAGE_MARKER])
        if value != FROZEN_IMAGE_MARKER:
            raise ValueError('stopped_worker_pinned_image_unavailable')
    else:
        value = checked.stdout.strip()
        state = dict(line.split('=', 1) for line in subprocess.check_output([
            'systemctl', 'show', 'fs-hermes-fc.service', '-p', 'ActiveState'],
            universal_newlines=True, timeout=10).splitlines())
    if not re.fullmatch('sha256:[a-f0-9]{64}', value):
        raise ValueError('current_worker_image_required')
    if state['ActiveState'] not in ('active', 'failed', 'inactive'):
        raise ValueError('worker_state_not_stable')
    return {'image': value, 'state': state['ActiveState'],
            'source': 'configured_unit_and_local_image' if checked.returncode else 'container'}


def worker_image(*, allow_stopped=False):
    return worker_observation(allow_stopped=allow_stopped)['image']


def native_path_info(path):
    """Check non-file dependencies without the frozen regular-file writer guard."""
    info = None
    for current in reversed((path, *path.parents)):
        try:
            info = current.lstat()
        except FileNotFoundError:
            info = None
            continue
        if stat.S_ISLNK(info.st_mode) or (current != path and not stat.S_ISDIR(info.st_mode)):
            raise ValueError('native_dependency_link_or_parent')
    return info


def native_dependencies(base, root):
    cli = base.rooted(root, NATIVE_CLI)
    base.no_target_link(cli)
    info = cli.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode)) != (0,0,0o755) or
            base.digest(cli) != NATIVE_CLI_SHA):
        raise ValueError('native_docker_cli_drift')
    socket = base.rooted(root, '/run/docker.sock')
    sock = native_path_info(socket)
    if sock is None or not stat.S_ISSOCK(sock.st_mode) or sock.st_uid != 0 or stat.S_IMODE(sock.st_mode) != 0o660:
        raise ValueError('native_docker_socket_unavailable')
    if root == Path('/'):
        user = subprocess.check_output(['docker','inspect','--format','{{.Config.User}}','fs-hermes-fc'],text=True,timeout=10).strip()
        if user != '9876:9876':
            raise ValueError('native_worker_user_drift')
    return {'cli':{'path':NATIVE_CLI,'sha256':NATIVE_CLI_SHA,'size':info.st_size,'uid':0,'gid':0,'mode':'0o755'},
            'socket':{'path':'/run/docker.sock','uid':sock.st_uid,'gid':sock.st_gid,'mode':oct(stat.S_IMODE(sock.st_mode)),
                      'inode':sock.st_ino,'device':sock.st_dev}, 'worker_user':'9876:9876'}


def ensure_native_directories():
    """Create only the new runtime data roots; rollback never deletes user data."""
    import os
    for name in (NATIVE_ROOT,NATIVE_ROOT+'/profiles',NATIVE_ROOT+'/workspaces',NATIVE_EMPTY_SOURCE):
        path = Path(name)
        info = native_path_info(path)
        wanted = (0,0,0o555) if name == NATIVE_EMPTY_SOURCE else (9876,9876,0o700)
        if info is None:
            path.mkdir(mode=wanted[2],parents=False)
            os.chown(path,wanted[0],wanted[1])
        info = native_path_info(path)
        if not stat.S_ISDIR(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode)) != wanted:
            raise ValueError('native_directory_owner_mode')
        if name == NATIVE_EMPTY_SOURCE and any(path.iterdir()):
            raise ValueError('native_empty_backend_home_changed')


def native_legacy_daily_guard(base, root):
    """Pin the unchanged host entry; never grant its private parent a code exception."""
    path=base.rooted(root,NATIVE_LEGACY_DAILY)
    info=native_path_info(path)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or
            (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(0,0,0o644) or
            base.digest(path)!=NATIVE_LEGACY_DAILY_SHA):
        raise ValueError('native_legacy_daily_drift')


def native_runtime_readiness():
    """Check the unchanged nonroot worker really reaches its fixed Docker daemon."""
    expected_contract={'version':'native_docker_v1','root':NATIVE_ROOT,'image':FROZEN_IMAGE_MARKER,
                       'docker_binary':'/opt/fs-native-bin/docker','docker_sha256':NATIVE_CLI_SHA,'uid':9876,'gid':9876}
    contract=Path(NATIVE_EXTRA_TARGETS['runtime/native-backend.json'])
    if contract.is_symlink() or json.loads(contract.read_bytes()) != expected_contract:
        raise ValueError('native_control_contract_drift')
    user=subprocess.check_output(['docker','inspect','--format','{{.Config.User}}','fs-hermes-fc'],text=True,timeout=10).strip()
    if user!='9876:9876':
        raise ValueError('native_control_user_readback')
    answer = subprocess.check_output(['docker','exec','fs-hermes-fc','/opt/fs-native-bin/docker',
                                     'version','--format','{{.Client.Version}}|{{.Server.Version}}'],
                                    text=True,timeout=15).strip()
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+_-]*\|[0-9][A-Za-z0-9.+_-]*',answer):
        raise ValueError('native_control_daemon_unavailable')
    mounts = json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Mounts}}','fs-hermes-fc'],
                                               text=True,timeout=10))
    expected = {'/opt/fs-native-bin/docker':(NATIVE_CLI,False),
                '/var/run/docker.sock':('/run/docker.sock',True),
                NATIVE_ROOT:(NATIVE_ROOT,True),'/opt/fs-native-backend-home':(NATIVE_EMPTY_SOURCE,False),
                NATIVE_DAILY_CONTAINER:(NATIVE_EXTRA_TARGETS['approval/daily_review.py'],False)}
    selected=[row for row in mounts if row['Destination'] in expected]
    actual = {row['Destination']:(row['Source'],row['RW']) for row in selected}
    if (actual != expected or len(selected)!=len(expected) or
            any(row['Destination'].startswith(('/opt/fs-native-',NATIVE_ROOT+'/',NATIVE_DAILY_CONTAINER.rsplit('/',1)[0]+'/'))
                and row['Destination'] not in expected for row in mounts)):
        raise ValueError('native_control_mount_readback')


def running_worker(manifest):
    if worker_observation() != {'image': manifest['workerImageId'], 'state': 'active', 'source': 'container'}:
        raise ValueError('worker_diagnostics_running_container_required')


def quiescent(base, root, archive_source=None, archive_exception=None, archive_sha=None):
    # The original requests/provider fences remain, with both conversation lanes,
    # tracking and learning added before either install or rollback can restart.
    for name, table, states in (
        ('conversations/conversations.db', 'turns', ('preparing', 'dispatch_unknown', 'queued', 'running', 'stopping')),
        ('pricing-reviews/conversations.db', 'turns', ('preparing', 'dispatch_unknown', 'queued', 'running', 'stopping')),
        ('tasks.sqlite3', 'tasks', ('QUEUED', 'DISPATCH_UNKNOWN', 'RUNNING', 'VALIDATING', 'NEEDS_RECONCILE')),
        ('tasks.sqlite3', 'learning_events', ('running', 'unknown')),
        ('customer-tracking/tracking.db', 'scan_jobs', ('pending',)),
        ('customer-tracking/tracking.db', 'milestones', ('claimed', 'creating', 'dispatch_unknown', 'queued', 'running'))):
        path = base.rooted(root, '/var/lib/fs-hermes-fc/fs/' + name)
        base.no_target_link(path)
        if not path.exists():
            if name == 'conversations/conversations.db' or name == 'tasks.sqlite3':
                raise ValueError('existing_material_task_store_required')
            continue
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                if table != 'learning_events':
                    raise ValueError('unknown_material_store_schema')
                continue
            query = 'SELECT count(*) FROM ' + table + ' WHERE state IN (' + ','.join('?' for _ in states) + ')'
            if db.execute(query, states).fetchone()[0]:
                if ARCHIVE_MODE and name=='conversations/conversations.db' and table=='turns':
                    checked=archive_check(base,root,archive_source,archive_sha)
                    if checked!=archive_exception:raise ValueError('archive_exception_CAS_drift')
                    if not db.execute(query+' AND id<>?',(*states,checked['turn_id'])).fetchone()[0]:continue
                raise ValueError('active_or_unknown_material_task')


def archive_usage_metadata(base, root):
    """Only this runtime ledger uses a fresh CAS, never a historical code hash."""
    path=base.rooted(root,ARCHIVE_USAGE_LEDGER)
    base.no_target_link(path)
    before=path.lstat()
    def boundary(info):
        return (stat.S_ISREG(info.st_mode) and info.st_nlink==1 and
                (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))==(0,0,0o600))
    if not boundary(before):raise ValueError('archive_usage_boundary_drift')
    with os.fdopen(os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)),'rb') as stream:
        opened=os.fstat(stream.fileno())
        if (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino):raise ValueError('archive_usage_changed')
        digest=hashlib.sha256(stream.read()).hexdigest()
    after=path.lstat();base.no_target_link(path)
    if (not boundary(after) or
            (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)):
        raise ValueError('archive_usage_changed')
    return dict(path=ARCHIVE_USAGE_LEDGER,sha256=digest,owner='0:0',mode='0o600')


def archive_rollback_guard(base, journal, root):
    """Never restore archive-blind before bytes after maintenance committed.

    No production module/store import, DDL, state mutation or recovery here.
    Before the first tombstone normal original rollback remains available.
    """
    if journal.get('manifest',{}).get('nativeArchive') is not True:
        return
    targets={'/opt/fs-hermes-fc/'+name for name in (
        'conversation_store.py','conversation_native.py','conversation_service.py')}
    if not any(row.get('target') in targets for row in journal.get('files',[])):
        return
    path=base.rooted(root,'/var/lib/fs-hermes-fc/fs/conversations/conversations.db')
    base.no_target_link(path)
    if not path.is_file():raise ValueError('archive_rollback_ledger_missing')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='synthetic_turn_archives'").fetchone()
        if exists and db.execute('SELECT 1 FROM synthetic_turn_archives LIMIT 1').fetchone():
            if (journal.get('manifest',{}).get('nativeCapabilities') is True and NATIVE_CAPABILITIES_MODE and
                    any(r.get('target')=='/opt/fs-hermes-fc/conversation_store.py' and r.get('beforeSha256')==CAPABILITIES_STORE_BEFORE_SHA for r in journal.get('files',[]))):
                return  # Original rollback still CAS-verifies these known archive-aware backup bytes.
            raise ValueError('archived_unknown_requires_archive_aware_forward_repair')


def load_base():
    approved = json.loads((HERE / 'approved-manifest.json').read_text('utf-8'))
    if approved.get('nativeComposerStatic') is True:
        if any(approved.get(k) is True for k in ('nativeCapabilities','nativeArchive','nativeAdmission','nativeChat',
                'materialExecution','materialGuard','bindingsAuth','materialStream','materialTransport',
                'workerDiagnostics','goalTaskIndexCompat','materialDiagnostics')):
            raise ValueError('conflicting_material_followup_modes')
        configure_native_composer_static()
        # The original validate runs before guards. Guards replace this view
        # with the fixed successful proof before checking any current file.
        COMPOSER_STATIC_METADATA.clear()
        COMPOSER_STATIC_METADATA.update({r['path']:dict(r) for r in approved['unchangedRequired']})
    if approved.get('nativeArchive') is True:
        if any(approved.get(key) is True for key in ('nativeAdmission','nativeChat','materialGuard','bindingsAuth','materialStream','materialTransport','workerDiagnostics','goalTaskIndexCompat','materialDiagnostics')):
            raise ValueError('conflicting_material_followup_modes')
        if approved.get('nativeCapabilities') is True:configure_native_capabilities()
        else:configure_native_archive()
        global ARCHIVE_PROTECTED
        ARCHIVE_PROTECTED={r['path']:r['sha256'] for r in approved['unchangedRequired']}
    if approved.get('nativeAdmission') is True:
        configure_native_admission()
    elif approved.get('nativeChat') is True:
        configure_native_chat()
    elif approved.get('materialGuard') is True:
        configure_material_guard()
    elif approved.get('bindingsAuth') is True:
        configure_bindings_auth()
    elif approved.get('materialStream') is True:
        configure_material_stream()
    elif approved.get('materialTransport') is True:
        configure_material_transport()
    elif approved.get('workerDiagnostics') is True:
        configure_worker_diagnostics()
    elif approved.get('goalTaskIndexCompat') is True:
        configure_task_index_compat()
    elif approved.get('materialDiagnostics') is True:
        configure_diagnostics()
    elif approved.get('materialExecution') is True:
        configure_execution()
    base = frozen()
    git_baseline = None
    if approved.get('installedBaseline'):
        raw = (HERE / 'payload-manifest.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != approved['approvedPayloadSha256']:
            raise ValueError('installed_git_descriptor_drift')
        git_baseline = json.loads(raw).get('installed_baseline')
    validate = base.validate

    def exact(manifest, stage):
        if COMPOSER_STATIC_MODE and (manifest.get('nativeComposerStatic') is not True or
                manifest.get('materialStaticOnly') is not True or len(manifest.get('files',[]))!=1 or
                manifest.get('materialChangedTargets')!=list(TARGETS.values()) or
                manifest['files'][0].get('beforeSha256')!=COMPOSER_BEFORE_SHA or
                manifest['files'][0].get('sha256')!=COMPOSER_AFTER_SHA or
                len(manifest.get('unchangedRequired',[]))!=778):
            raise ValueError('exact_composer_static_delta_required')
        controlled = ARCHIVE_MODE or DIAGNOSTICS_MODE or TASK_INDEX_MODE or WORKER_DIAGNOSTICS_MODE or TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE or NATIVE_MODE
        marker = 'nativeArchive' if ARCHIVE_MODE else 'nativeAdmission' if NATIVE_ADMISSION_MODE else 'nativeChat' if NATIVE_MODE else 'materialGuard' if GUARD_MODE else 'bindingsAuth' if BINDINGS_MODE else 'materialStream' if STREAM_MODE else 'materialTransport' if TRANSPORT_MODE else 'workerDiagnostics' if WORKER_DIAGNOSTICS_MODE else 'goalTaskIndexCompat' if TASK_INDEX_MODE else 'materialDiagnostics'
        allowed = tuple(TARGETS) if ARCHIVE_MODE else (NATIVE_ADMISSION_CANDIDATE,) if NATIVE_ADMISSION_MODE else NATIVE_ALLOWED if NATIVE_MODE else (BINDINGS_CANDIDATE,) if BINDINGS_MODE else (TRANSPORT_CANDIDATE,) if TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE else ('runtime/hermes_worker.py',) if WORKER_DIAGNOSTICS_MODE else ('runtime/conversation_goal_tasks.py',) if TASK_INDEX_MODE else ('http/conversation_http.py', 'http/range_api.py')
        if controlled and (manifest.get('nativeCapabilities',False) is not NATIVE_CAPABILITIES_MODE or manifest.get(marker) is not True or
                NATIVE_CAPABILITIES_MODE and manifest.get('nativeStaticBaseline')!=CAPABILITIES_STATIC_PROOF or
                any(manifest.get(key) is True for key in ('nativeArchive','nativeAdmission','nativeChat','materialGuard', 'bindingsAuth', 'materialStream', 'materialTransport', 'workerDiagnostics', 'goalTaskIndexCompat', 'materialDiagnostics') if key != marker) or
                manifest.get('installedBaseline') != INSTALLED_PROOF or
                manifest.get('runtimeBefore') != manifest.get('runtimeRequired') or
                manifest.get('workerImageSource') != 'container' or
                ARCHIVE_MODE and (len(manifest.get('files',[]))!=len(TARGETS) or manifest.get('materialChangedTargets')!=
                    ([TARGETS[n] for n in CAPABILITIES_CHANGED] if NATIVE_CAPABILITIES_MODE else list(TARGETS.values()))) or
                NATIVE_ADMISSION_MODE and manifest.get('materialChangedTargets') != [TARGETS[NATIVE_ADMISSION_CANDIDATE]] or
                WORKER_DIAGNOSTICS_MODE and manifest.get('materialChangedTargets') != [TARGETS['runtime/hermes_worker.py']] or
                (TRANSPORT_MODE or STREAM_MODE or GUARD_MODE) and manifest.get('materialChangedTargets') != [TRANSPORT_TARGET]
                or BINDINGS_MODE and manifest.get('materialChangedTargets') != [TARGETS[BINDINGS_CANDIDATE]] or
                (TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE) and len(manifest.get('unchangedRequired', [])) != len(protected_paths(base)) or
                (NATIVE_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE) and len(manifest.get('files', [])) != len(TARGETS) or
                manifest.get('materialChangedTargets') != [r['target'] for r in manifest.get('files', [])
                                                          if r['beforeSha256'] != r['sha256']] or
                any(r['beforeSha256'] != r['sha256'] and r['candidate'] not in allowed for r in manifest.get('files', []))):
            raise ValueError('exact_native_admission_delta_required' if NATIVE_ADMISSION_MODE else 'exact_material_guard_delta_required' if GUARD_MODE else 'exact_bindings_auth_delta_required' if BINDINGS_MODE else 'exact_material_stream_delta_required' if STREAM_MODE else 'exact_material_transport_delta_required' if TRANSPORT_MODE else 'exact_worker_diagnostics_delta_required' if WORKER_DIAGNOSTICS_MODE else 'exact_goal_task_index_delta_required' if TASK_INDEX_MODE else 'exact_material_diagnostics_delta_required')
        if manifest != approved or manifest.get('scope') != SCOPE:
            raise ValueError('exact_material_manifest_required')
        if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:
            raise ValueError('material_readonly_business_boundary')
        observed = datetime.fromisoformat(manifest['baselineObservedAt'])
        if observed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 3600:
            raise ValueError('fresh_material_baseline_required')
        if not re.fullmatch('sha256:[a-f0-9]{64}', manifest.get('workerImageId', '')):
            raise ValueError('material_worker_image_required')
        installed = manifest.get('installedBaseline')
        if installed is not None and installed != INSTALLED_PROOF:
            raise ValueError('exact_installed_release_required')
        if installed and (not isinstance(git_baseline, dict)
                          or git_baseline.get('source_commit') != INSTALLED_COMMIT
                          or set(git_baseline.get('files', {})) != set(TARGETS)):
            raise ValueError('installed_git_baseline_required')
        if BINDINGS_MODE and (git_baseline['files'].get(BINDINGS_CANDIDATE) != BINDINGS_BEFORE_SHA
                or git_baseline['files'].get(TRANSPORT_CANDIDATE) != BINDINGS_TRANSPORT_SHA):
            raise ValueError('exact_installed_bindings_baseline_required')
        if (STREAM_MODE or GUARD_MODE) and git_baseline['files'].get(TRANSPORT_CANDIDATE) != (GUARD_BEFORE_SHA if GUARD_MODE else STREAM_BEFORE_SHA):
            raise ValueError('exact_installed_guard_transport_required' if GUARD_MODE else 'exact_installed_stream_transport_required')
        for row in manifest.get('files', []):
            wrong_before = (row.get('beforeSha256') != git_baseline['files'][row['candidate']] if installed
                            else (row.get('beforeSha256') is None) != (row['candidate'] in NEW))
            if (wrong_before
                    or row.get('owner') != '0:0'
                    or row.get('mode') != ('0o600' if row['target'] == NGINX else '0o644')):
                raise ValueError('material_existing_new_or_mode_boundary')
        if manifest.get('runtimeRequired') != {unit: {'ActiveState': 'active'} for unit in (
                'fs-business-range.service', 'fs-hermes-fc.service', 'nginx.service')}:
            raise ValueError('material_active_services_required')
        before = manifest.get('runtimeBefore', {})
        if (set(before) != set(manifest['runtimeRequired'])
                or before['fs-business-range.service'] != {'ActiveState': 'active'}
                or before['nginx.service'] != {'ActiveState': 'active'}
                or before['fs-hermes-fc.service'] not in [
                    {'ActiveState': state} for state in ('active', 'inactive', 'failed')]
                or manifest.get('workerImageSource') not in ('container', 'configured_unit_and_local_image')
                or (manifest['workerImageSource'] == 'configured_unit_and_local_image'
                    and before['fs-hermes-fc.service']['ActiveState'] == 'active')):
            raise ValueError('material_runtime_before_required')
        static = manifest.get('materialStaticOnly', False)
        if type(static) is not bool or static and (
                not installed or manifest['runtimeBefore'] != manifest['runtimeRequired']
                or manifest['workerImageSource'] != 'container'
                or any(row['beforeSha256'] != row['sha256'] and not row['candidate'].startswith('frontend/')
                       for row in manifest['files'])):
            raise ValueError('exact_static_material_delta_required')
        if {row['path'] for row in manifest.get('unchangedRequired', [])} != protected_paths(base):
            raise ValueError('material_protected_set_changed')
        if NATIVE_MODE:
            dependencies = manifest.get('nativeDependencies')
            required = set(NEW) | {'unit/native-control.conf','runtime/hermes_worker.py','runtime/conversation_service.py',
                       'runtime/proxy_gateway.py','runtime/fs_inprocess.py','runtime/transport.py',
                       'frontend/index.html','frontend/conversation.css','frontend/conversation.js',
                       'approval/review_queue.py','approval/daily_review.py'}
            if NATIVE_ADMISSION_MODE:
                required = {NATIVE_ADMISSION_CANDIDATE}
                rows = {row['candidate']:row for row in manifest['files']}
                if (type(dependencies) is not dict or NEW or rows[NATIVE_ADMISSION_CANDIDATE]['beforeSha256'] != NATIVE_ADMISSION_BEFORE_SHA or
                        rows[NATIVE_ADMISSION_CANDIDATE]['sha256'] != NATIVE_ADMISSION_AFTER_SHA or
                        rows['unit/native-control.conf']['sha256'] != NATIVE_CURRENT_UNIT_SHA or
                        rows['runtime/native-backend.json']['sha256'] != hashlib.sha256(native_backend_bytes()).hexdigest() or
                        dependencies.get('socket',{}).get('gid') != NATIVE_SOCKET_GID):
                    raise ValueError('native_admission_existing_contract_required')
            changed = {row['candidate'] for row in manifest['files'] if row['beforeSha256'] != row['sha256']}
            if (type(dependencies) is not dict or dependencies.get('cli',{}).get('sha256') != NATIVE_CLI_SHA or
                    dependencies.get('worker_user') != '9876:9876' or not required <= changed or
                    len(manifest['unchangedRequired']) != len(protected_paths(base))):
                raise ValueError('native_complete_payload_and_dependencies_required')
        return validate(manifest, stage)

    base.validate = exact
    original_group = base.approved_daily_group
    base.approved_daily_group = lambda manifest, root, item, info: original_group(manifest, root, item, info) or (
        manifest.get('scope') == SCOPE and item == base.rooted(root, '/var/lib/fs-hermes-fc')
        and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 9876, 0o750))
    original_idle = base.hermes_quiescent

    def idle(root):
        if COMPOSER_STATIC_MODE:
            return  # The exact static page replaces no running task consumer.
        original_idle(root)
        quiescent(base,root,HERE/'candidate/runtime/conversation_store.py',approved.get('archiveException'),next((r['sha256'] for r in approved['files'] if r['candidate']=='runtime/conversation_store.py'),None))

    base.hermes_quiescent = idle
    if COMPOSER_STATIC_MODE:
        def static_file_fence(manifest, root):
            if manifest != approved:
                raise ValueError('exact_material_manifest_required')
            # Keep the original publisher/collector file locks. A static HTML
            # replacement needs neither task admission/DB transactions nor the
            # provider/report fence, which can stop a service on failure.
            return nullcontext()
        base.hermes_admission_fence = static_file_fence
        base.model_release_lock = static_file_fence
    original_guards = base.guards
    before_restart = True

    def guards(manifest, root, reader_stopped=False):
        # runtimeRequired is the successful postcondition, runtimeBefore is the
        # explicit observed precondition. Never fake an active worker to the
        # frozen checks, and retain every other guard/protected source check.
        if COMPOSER_STATIC_MODE and manifest != approved:
            raise ValueError('exact_material_manifest_required')
        if manifest.get('installedBaseline'):
            installed_baseline(root, git_baseline)
        if COMPOSER_STATIC_MODE and (len(manifest['unchangedRequired'])!=778 or
                {r['path'] for r in manifest['unchangedRequired']}!=set(COMPOSER_STATIC_METADATA)):
            raise ValueError('composer_static_protected_set_drift')
        if COMPOSER_STATIC_MODE or ARCHIVE_MODE or NATIVE_MODE or WORKER_DIAGNOSTICS_MODE or TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE:
            running_worker(manifest)
        if NATIVE_MODE and native_dependencies(base, root) != manifest['nativeDependencies']:
            raise ValueError('native_dependencies_cas_drift')
        if NATIVE_MODE:
            native_legacy_daily_guard(base,root)
        if before_restart and manifest.get('scope') == SCOPE:
            if manifest['runtimeBefore']['fs-hermes-fc.service'] != {'ActiveState': 'active'}:
                observed = worker_observation(allow_stopped=True)
                if (observed['image'] != manifest['workerImageId']
                        or observed['source'] != manifest['workerImageSource']):
                    raise ValueError('material_recovery_image_source_drift')
            manifest = dict(manifest, runtimeRequired=manifest['runtimeBefore'])
        if ARCHIVE_MODE or COMPOSER_STATIC_MODE:
            for row in manifest['unchangedRequired']:
                if row['path']==ARCHIVE_USAGE_LEDGER:
                    current=archive_usage_metadata(base,root)
                    if current!=row:raise ValueError('archive_usage_cas_drift')
                elif row['sha256']!=ARCHIVE_PROTECTED.get(row['path']):
                    raise ValueError('archive_static_protection_drift')
                if (COMPOSER_STATIC_MODE or NATIVE_CAPABILITIES_MODE) and any(row.get(k)!=COMPOSER_STATIC_METADATA[row['path']].get(k) for k in ('owner','mode')):
                    raise ValueError('composer_static_protected_metadata_drift')
                info=base.rooted(root,row['path']).stat()
                if row['owner']!=str(info.st_uid)+':'+str(info.st_gid) or row['mode']!=oct(stat.S_IMODE(info.st_mode)):
                    raise ValueError('archive_protected_mode_owner_drift')
        return original_guards(manifest, root, reader_stopped=reader_stopped)

    base.guards = guards
    original_atomic, original_apply = base.atomic, base.apply
    publish_root = Path('/')
    restoring_native = False
    original_rollback_journal = base.rollback_journal

    def rollback_journal(backup, journal, root):
        nonlocal restoring_native
        archive_rollback_guard(base,journal,root)
        result = original_rollback_journal(backup, journal, root)
        if approved.get('nativeChat') or approved.get('nativeAdmission'):
            if any(base.digest(base.rooted(root,row['target'])) != row['beforeSha256'] for row in journal['files']):
                raise ValueError('native_rollback_bytes_incomplete')
            restoring_native = True
        return result

    if approved.get('nativeChat') or approved.get('nativeAdmission') or approved.get('nativeArchive'):
        base.rollback_journal = rollback_journal

    def atomic(path, payload, mode=0o644):
        # Keep the original writer/journal and every per-row guard. Static-only
        # follow-ups leave identical active targets (including runtime) untouched.
        if approved.get('nativeArchive') or approved.get('nativeAdmission') or approved.get('nativeChat') or approved.get('materialStaticOnly') or approved.get('materialDiagnostics') or approved.get('goalTaskIndexCompat') or approved.get('workerDiagnostics') or approved.get('materialTransport') or approved.get('materialStream') or approved.get('bindingsAuth') or approved.get('materialGuard'):
            for row in approved['files']:
                if path == base.rooted(publish_root, row['target']) and row['beforeSha256'] == row['sha256']:
                    if (hashlib.sha256(payload).hexdigest() != row['sha256']
                            or base.digest(path) != row['sha256'] or mode != int(row['mode'], 8)):
                        raise ValueError('unchanged_static_target_drift')
                    return
        return original_atomic(path, payload, mode)

    def apply(manifest, stage, approved_sha, manifest_bytes, release_id, root=Path('/')):
        nonlocal publish_root
        publish_root = root
        return original_apply(manifest, stage, approved_sha, manifest_bytes, release_id, root)

    base.atomic, base.apply = atomic, apply
    original_inspect = base.inspect

    def inspect(manifest, stage, root=Path('/')):
        result = original_inspect(manifest, stage, root)
        if COMPOSER_STATIC_MODE or ARCHIVE_MODE or NATIVE_MODE or WORKER_DIAGNOSTICS_MODE or TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE:
            running_worker(manifest)
        if NATIVE_MODE and native_dependencies(base, root) != manifest['nativeDependencies']:
            raise ValueError('native_dependencies_cas_drift')
        if ARCHIVE_MODE or NATIVE_ADMISSION_MODE:
            native_runtime_readiness()
        if root == Path('/'):
            for row in manifest['files']:
                path = base.rooted(root, row['target'])
                if path.exists():
                    info = path.stat()
                    if (info.st_uid, info.st_gid, oct(stat.S_IMODE(info.st_mode))) != (0, 0, row['mode']):
                        raise ValueError('material_target_owner_mode_drift')
            if not (NATIVE_MODE or WORKER_DIAGNOSTICS_MODE or TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE) and worker_image(allow_stopped=True) != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            if COMPOSER_STATIC_MODE:
                return result  # No staged/runtime imports for a single static HTML replacement.
            # Import definitions only; no service instance, model or source query.
            program = ("import sys;from pathlib import Path;"
                       "sys.path[:0]=sys.argv[1:];"
                       "import conversation_service,conversation_http,conversation_file_tools,conversation_files;"
                       "assert Path(conversation_service.__file__).parent==Path(sys.argv[1]);"
                       "import openpyxl,et_xmlfile")
            if EXECUTION_MODE:
                program += ';import conversation_material_runs,conversation_goals,conversation_goal_tasks,material_execution,b2_goal_host,b2_goal_state'
            if TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE:
                program += ';import transport;assert Path(transport.__file__).parent==Path(sys.argv[1])'
            if NATIVE_MODE:
                program += ';import native_chat,conversation_native,transport;assert Path(conversation_native.__file__).parent==Path(sys.argv[1])'
            checked = subprocess.run(['/opt/python39/bin/python3.9', '-I', '-B', '-c', program,
                                      str((stage / 'candidate/runtime').resolve()),
                                      str((stage / 'candidate/http').resolve()), '/opt/fs-hermes-fc',
                                      '/opt/fs-exact-range-20261001'], capture_output=True, timeout=25)
            if checked.returncode:
                raise ValueError('material_composed_import_failed')
        return result

    base.inspect = inspect
    original_restart = base.restart_for
    helper = HERE / 'release_readiness.py'
    if hashlib.sha256(helper.read_bytes()).hexdigest() != approved.get('readinessSha256'):
        raise ValueError('current_readiness_helper_changed')
    spec = importlib.util.spec_from_file_location('material_readiness', helper)
    readiness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(readiness)

    def restart(manifest, admission_fence=None):
        nonlocal before_restart
        before_restart = False
        if manifest.get('nativeCapabilities'):
            if admission_fence is None:raise ValueError('native_admission_fence_required')
            admission_fence.stop_then_unlock_database()
            readiness.restart_with_hermes_readiness(base,original_restart,dict(manifest,scope=base.HERMES_WORKER_SCOPE),admission_fence)
            readiness.restart_with_hermes_readiness(base,original_restart,dict(manifest,scope=base.DEEP_SCOPE),admission_fence)
            running_worker(manifest);native_runtime_readiness();base.guards(manifest,publish_root)
            return
        if manifest.get('nativeArchive') or manifest.get('nativeAdmission'):
            if admission_fence is None:
                raise ValueError('native_admission_fence_required')
            admission_fence.stop_then_unlock_database()
            result = readiness.restart_with_hermes_readiness(base, original_restart,
                dict(manifest, scope=base.DEEP_SCOPE), admission_fence)
            running_worker(manifest)
            native_runtime_readiness()
            base.guards(manifest, publish_root)
            return result
        if manifest.get('nativeChat'):
            if admission_fence is None:
                raise ValueError('native_admission_fence_required')
            if publish_root == Path('/') and not restoring_native:
                ensure_native_directories()
            subprocess.run(['systemctl','daemon-reload'],check=True)
            admission_fence.stop_then_unlock_database()
            readiness.restart_with_hermes_readiness(base, original_restart,
                dict(manifest, scope=base.HERMES_WORKER_SCOPE), admission_fence)
            readiness.restart_with_hermes_readiness(base, original_restart,
                dict(manifest, scope=base.DEEP_SCOPE), admission_fence)
            running_worker(manifest)
            if not restoring_native:
                native_runtime_readiness()
            base.guards(manifest, publish_root)
            return
        if manifest.get('workerDiagnostics'):
            # No host code changed: retain the original admission fence while
            # restarting only the worker, using its original capabilities probe.
            result = readiness.restart_with_hermes_readiness(base, original_restart,
                dict(manifest, scope=base.HERMES_WORKER_SCOPE), admission_fence)
            running_worker(manifest)
            base.guards(manifest, publish_root)
            return result
        if manifest.get('materialStaticOnly'):
            if worker_image() != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            base.guards(manifest, publish_root)
            return  # Static bytes only: no worker/HTTP restart or Nginx reload.
        if manifest.get('materialDiagnostics') or manifest.get('goalTaskIndexCompat') or manifest.get('materialTransport') or manifest.get('materialStream') or manifest.get('bindingsAuth') or manifest.get('materialGuard'):
            # Same original admission fence and DEEP restart on install/rollback;
            # only the existing HTTP process loads changed bytes. Worker/Nginx
            # targets and their running processes are not changed by this mode.
            admission_fence.stop_then_unlock_database()
            result = readiness.restart_with_hermes_readiness(base, original_restart,
                dict(manifest, scope=base.DEEP_SCOPE), admission_fence)
            if TRANSPORT_MODE or STREAM_MODE or BINDINGS_MODE or GUARD_MODE:
                running_worker(manifest)
            elif worker_image() != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            base.guards(manifest, publish_root)
            return result
        if manifest.get('scope') == SCOPE:
            subprocess.run(['nginx', '-t'], check=True, capture_output=True)
        result = readiness.restart_with_hermes_readiness(base, original_restart, manifest, admission_fence)
        if manifest.get('scope') == SCOPE:
            if worker_image() != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            base.guards(manifest, Path('/'))
            subprocess.run(['systemctl', 'reload', 'nginx.service'], check=True)
        return result

    base.restart_for = restart
    return base


def archive_synthetic_maintenance(release_id, approved_sha, root=Path('/')):
    """Post-apply maintenance under the original locks; no task POST or retry."""
    if not re.fullmatch(r'nav-[0-9]{8}T[0-9]{6}Z',release_id):raise ValueError('fixed release id required')
    approved=json.loads((HERE/'approved-manifest.json').read_bytes())
    raw=(HERE/'approved-manifest.json').read_bytes()
    if approved.get('nativeCapabilities') or approved.get('nativeArchive') is not True or hashlib.sha256(raw).hexdigest()!=approved_sha:
        raise ValueError('exact_archive_maintenance_manifest_required')
    base=load_base();backup=base.rooted(root,'/var/backups/fs-navigation-20261006/'+release_id)
    base.no_target_link(backup/'journal.json');journal=json.loads((backup/'journal.json').read_bytes())
    if (journal.get('manifest')!=approved or journal.get('approvedManifestSha256')!=approved_sha or
            journal.get('status')!='applied-awaiting-actual-http-role-acceptance'):
        raise ValueError('archive_requires_successful_apply')
    with base.locks(root),base.live_lock(approved,root),base.hermes_admission_fence(approved,root),base.model_release_lock(approved,root):
        if any(base.digest(base.rooted(root,r['target']))!=r['sha256'] for r in approved['files']):
            raise ValueError('archive_installed_consumer_drift')
        base.guards(approved,root)
        store_sha=next(r['sha256'] for r in approved['files'] if r['candidate']=='runtime/conversation_store.py')
        checked=archive_check(base,root,HERE/'candidate/runtime/conversation_store.py',store_sha)
        if checked!=approved['archiveException']:raise ValueError('archive_exception_CAS_drift')
        module=archive_store_module(base.rooted(root,TARGETS['runtime/conversation_store.py']),store_sha)
        store=module.ConversationStore.__new__(module.ConversationStore)
        store.path=base.rooted(root,'/var/lib/fs-hermes-fc/fs/conversations/conversations.db')
        # Empty new audit table is normally initialized by the restarted service.
        # If readiness returned without it, refuse rather than bypass that consumer.
        with store.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='synthetic_turn_archives'").fetchone():raise ValueError('archive_consumer_schema_not_ready')
            owner=db.execute('SELECT owner FROM conversations WHERE id=?',(checked['cid'],)).fetchone()[0]
        return store.archive_synthetic_unknown(owner)


if __name__ == '__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='archive-synthetic':
        import argparse
        parser=argparse.ArgumentParser();parser.add_argument('action');parser.add_argument('--release-id',required=True);parser.add_argument('--approved-manifest-sha',required=True)
        args=parser.parse_args();print(json.dumps(archive_synthetic_maintenance(args.release_id,args.approved_manifest_sha)))
    else:load_base().main()
