"""UID-scoped loopback-only runtime policy; no global firewall flush or provider key."""
import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess

UID=9876
CHAIN='FS_HERMES_FC'


def command(args,check=True):
    return subprocess.run(args,check=check,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)


def identity():
    import pwd
    entry=pwd.getpwnam('fs-hermes-fc')
    if entry.pw_uid!=UID or entry.pw_gid!=UID or entry.pw_shell not in ('/sbin/nologin','/usr/sbin/nologin'):
        raise ValueError('runtime_identity_drift')
    if subprocess.check_output(['id','-G','fs-hermes-fc'],universal_newlines=True).strip()!=str(UID):raise ValueError('runtime_extra_groups')
    return entry


def directory(path,uid,gid,mode):
    p=Path(path)
    if any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('linked_runtime_directory')
    p.mkdir(parents=True,exist_ok=True,mode=mode);os.chown(p,uid,gid);p.chmod(mode)


def rules(binary):
    if binary=='iptables':
        return [['-d','127.0.0.1/32','-p','tcp','--dport','8940','-j','ACCEPT'],
                ['-d','127.0.0.1/32','-p','tcp','--dport','8941','-j','ACCEPT'],
                ['-d','127.0.0.1/32','-p','tcp','--sport','8941','-m','conntrack','--ctstate','ESTABLISHED','-j','ACCEPT'],
                ['-j','REJECT']]
    return [['-j','REJECT']]


def apply():
    identity()
    image='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
    if subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',image],universal_newlines=True).strip()!=image:
        raise ValueError('fixed_runtime_image_missing')
    # No user-namespace remapping: firewall ownership must match host UID.
    info=json.loads(subprocess.check_output(['docker','info','--format','{{json .SecurityOptions}}'],universal_newlines=True))
    if any('userns' in item or 'rootless' in item for item in info):raise ValueError('docker_uid_mapping_unknown')
    for path,uid,gid,mode in [('/run/fs-hermes-fc',0,UID,0o750),('/run/fs-hermes-fc/admissions',0,UID,0o2750),
            ('/var/lib/fs-hermes-fc',0,UID,0o750),('/var/lib/fs-hermes-fc/profile',UID,UID,0o700)]:directory(path,uid,gid,mode)
    key=Path('/run/fs-hermes-fc/api-key')
    if key.is_symlink():raise ValueError('linked_runtime_key')
    # Rotating this local control key stops old callers without copying any key.
    key.write_text(secrets.token_urlsafe(32),encoding='ascii');os.chown(key,0,UID);key.chmod(0o640)
    for binary in ('iptables','ip6tables'):
        exists=command([binary,'-S',CHAIN],False)
        if exists.returncode==0:
            # Only this exact owned chain is acceptable; never overwrite unknown rules.
            expected=len(rules(binary))
            if len([l for l in exists.stdout.splitlines() if l.startswith('-A ')])!=expected:raise ValueError('firewall_chain_drift')
            for rule in rules(binary):command([binary,'-C',CHAIN]+rule)
        else:
            command([binary,'-N',CHAIN])
            for rule in rules(binary):command([binary,'-A',CHAIN]+rule)
        jump=['-m','owner','--uid-owner',str(UID),'-j',CHAIN]
        if command([binary,'-C','OUTPUT']+jump,False).returncode:command([binary,'-I','OUTPUT','1']+jump)
    print(json.dumps({'uid':UID,'egress':['127.0.0.1:8940','127.0.0.1:8941'],'ipv6':'denied','provider_key_present':False}))


def remove():
    identity()
    for binary in ('iptables','ip6tables'):
        if command([binary,'-S',CHAIN],False).returncode:continue
        for rule in rules(binary):command([binary,'-C',CHAIN]+rule)
        jump=['-m','owner','--uid-owner',str(UID),'-j',CHAIN]
        if command([binary,'-C','OUTPUT']+jump,False).returncode==0:command([binary,'-D','OUTPUT']+jump)
        for rule in rules(binary):command([binary,'-D',CHAIN]+rule)
        command([binary,'-X',CHAIN])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['apply','remove']);args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError('release_identity_required')
    (apply if args.action=='apply' else remove)()
