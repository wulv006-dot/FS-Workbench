"""Offline diagnostic transport, not an FS implementation or property oracle."""
import json
import os
import subprocess
import sys


def read_sources(repo, revision, paths):
    result={}
    for name,path in paths.items():
        # Local objects only. A missing object is an error, never a passed probe.
        process=subprocess.run(['git','-C',str(repo),'show',revision+':'+path],
            capture_output=True,check=True,env=dict(os.environ,GIT_NO_LAZY_FETCH='1'))
        result[name]=process.stdout
    return result


def install_guard():
    def deny(event,args):
        if event in {'socket.connect','socket.connect_ex','socket.bind','socket.getaddrinfo',
                     'socket.sendto','subprocess.Popen','os.system','os.posix_spawn'}:
            raise RuntimeError('OFFLINE_DENY:'+event)
    sys.addaudithook(deny)


def run_diagnostic(script,repo):
    """Preserve observation and exit status, including intentional failures."""
    process=subprocess.run([sys.executable,'-I','-B',str(script)],capture_output=True,text=True,
        timeout=20,env=dict(os.environ,FS_ACCEPTANCE_REPO=str(repo),GIT_NO_LAZY_FETCH='1'))
    observation=None
    if process.stdout.strip():
        try:observation=json.loads(process.stdout)
        except ValueError:pass
    return {'returncode':process.returncode,'observation':observation,
            'stderr_present':bool(process.stderr.strip())}
