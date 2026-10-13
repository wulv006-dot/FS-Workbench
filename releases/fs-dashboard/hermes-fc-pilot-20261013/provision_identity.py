"""Explicitly approved, idempotent no-login pilot identity prerequisite."""
import argparse
import json
import os
import subprocess

UID=9876
NAME='fs-hermes-fc'

def inspect():
    import pwd,grp
    def find(fn,key):
        try:return fn(key)
        except KeyError:return None
    user=find(pwd.getpwnam,NAME);numeric=find(pwd.getpwuid,UID)
    group=find(grp.getgrnam,NAME);numeric_group=find(grp.getgrgid,UID)
    if numeric and numeric.pw_name!=NAME or numeric_group and numeric_group.gr_name!=NAME:raise ValueError('pilot_uid_collision')
    if user and (user.pw_uid!=UID or user.pw_gid!=UID or user.pw_shell not in ('/sbin/nologin','/usr/sbin/nologin')):raise ValueError('pilot_identity_drift')
    if group and (group.gr_gid!=UID or group.gr_mem):raise ValueError('pilot_group_drift')
    if user and subprocess.check_output(['id','-G',NAME],universal_newlines=True).strip()!=str(UID):raise ValueError('pilot_extra_groups')
    return {'user_present':user is not None,'group_present':group is not None,'name':NAME,'uid':UID,'no_login':True,'extra_authority':False}

def apply(approved):
    if os.geteuid()!=0 or not approved:raise PermissionError('approved_identity_prerequisite_required')
    before=inspect()
    if not before['group_present']:subprocess.run(['groupadd','--system','--gid',str(UID),NAME],check=True)
    if not before['user_present']:subprocess.run(['useradd','--system','--uid',str(UID),'--gid',str(UID),'--shell','/sbin/nologin','--no-create-home','--home-dir','/var/lib/fs-hermes-fc/profile',NAME],check=True)
    return inspect()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['inspect','apply']);parser.add_argument('--approved-fc-readonly-identity',action='store_true');args=parser.parse_args()
    print(json.dumps(inspect() if args.action=='inspect' else apply(args.approved_fc_readonly_identity)))
