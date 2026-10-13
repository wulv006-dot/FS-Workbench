"""Real UID/iptables socket checks inside a fresh CI network namespace only."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import shutil
import threading
import time

from network_guard import CHAIN,UID,rules

def connect(port,host='127.0.0.1'):
    with socket.create_connection((host,port),timeout=2) as sock:
        sock.sendall(b'probe');return sock.recv(8)

def listener(port,host='127.0.0.1'):
    sock=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET);sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    sock.bind((host,port));sock.listen();sock.settimeout(15)
    def serve():
        try:
            while True:
                conn,_=sock.accept()
                with conn:conn.recv(8);conn.sendall(b'ok')
        except OSError:pass
    thread=threading.Thread(target=serve,daemon=True);thread.start();return sock,thread

def worker():
    assert os.getuid()==UID
    assert connect(8940)==b'ok','approved_proxy_blocked'
    for host in ('127.0.0.1','::1'):
        try:connect(8899,host)
        except OSError:pass
        else:raise AssertionError('unapproved_local_service_reachable')
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('127.0.0.1',8941));sock.listen();sock.settimeout(15)
        print('ready',flush=True)
        conn,_=sock.accept()
        with conn:conn.recv(8);conn.sendall(b'ok')
    print(json.dumps({'uid':UID,'proxy_8940':'pass','runtime_8941_established_reply':'pass','other_local_ipv4':'denied','ipv6':'denied'}),flush=True)

def main():
    assert os.geteuid()==0,'CI_root_namespace_required'
    assert Path('/proc/self/ns/net').readlink()!=Path('/proc/1/ns/net').readlink(),'host_namespace_refused'
    subprocess.run(['/usr/sbin/ip','link','set','lo','up'],check=True)
    servers=[listener(8940),listener(8899),listener(8899,'::1')]
    assert connect(8899)==b'ok' and connect(8899,'::1')==b'ok','control_services_not_available'
    for binary in ('iptables','ip6tables'):
        executable='/usr/sbin/'+binary
        subprocess.run([executable,'-N',CHAIN],check=True)
        for rule in rules(binary):subprocess.run([executable,'-A',CHAIN]+rule,check=True)
        subprocess.run([executable,'-I','OUTPUT','1','-m','owner','--uid-owner',str(UID),'-j',CHAIN],check=True)
    def identity():os.setgroups([]);os.setgid(UID);os.setuid(UID)
    fixture=tempfile.TemporaryDirectory(prefix='hermes-uid-network-');folder=Path(fixture.name);folder.chmod(0o755)
    for name in ('network_smoke.py','network_guard.py'):
        target=folder/name;shutil.copyfile(Path(__file__).parent/name,target);target.chmod(0o444)
    child=subprocess.Popen([sys.executable,'-B',str(folder/'network_smoke.py'),'--worker'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,preexec_fn=identity)
    try:
        if child.stdout.readline().strip()!='ready':
            out,error=child.communicate(timeout=5)
            raise AssertionError(('worker_start_failed',out,error))
        assert connect(8941)==b'ok','runtime_response_blocked'
        out,error=child.communicate(timeout=15)
        assert child.returncode==0,(out,error)
        print(out.strip())
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)
        for sock,thread in servers:sock.close()
        fixture.cleanup()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');args=parser.parse_args()
    (worker if args.worker else main)()
