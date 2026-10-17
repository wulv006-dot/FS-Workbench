from pathlib import Path
import shlex
import unittest

HERE=Path(__file__).resolve().parent
BASE=HERE/'deps' if (HERE/'deps').is_dir() else HERE.parent/'hermes-fc-pilot-20261013'


class RuntimeIsolationTests(unittest.TestCase):
    def test_only_private_install_tmpfs_added_to_original_worker(self):
        original=next(l for l in (BASE/'fs-hermes-fc.service').read_text().splitlines() if l.startswith('ExecStart='))
        lines=(HERE/'source/worker-install-state-isolation.conf').read_text().splitlines()
        self.assertEqual([l for l in lines if l.startswith('ExecStart=')][0],'ExecStart=')
        changed=[l for l in lines if l.startswith('ExecStart=')][1]
        private='--tmpfs /profile/installs:rw,nosuid,nodev,uid=9876,gid=9876,mode=0700,size=134217728 '
        self.assertEqual(changed.count(private),1)
        self.assertEqual(changed.replace(private,''),original)

    def test_no_new_identity_network_provider_or_home(self):
        lines=(HERE/'source/worker-install-state-isolation.conf').read_text().splitlines()
        self.assertEqual([l for l in lines if l and not l.startswith('#') and not l.startswith('ExecStart=')],['[Service]'])
        args=shlex.split(next(l for l in lines if l.startswith('ExecStart=') and len(l)>10)[10:])
        for flag,value in [('--user','9876:9876'),('--network','host'),('--cap-drop','ALL')]:
            self.assertEqual(args[args.index(flag)+1],value)
        self.assertIn('--read-only',args);self.assertIn('HERMES_HOME=/profile',args)
        self.assertIn('sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',args)
        self.assertFalse(any('API_KEY=' in x or x=='--privileged' for x in args))


if __name__=='__main__':unittest.main()
