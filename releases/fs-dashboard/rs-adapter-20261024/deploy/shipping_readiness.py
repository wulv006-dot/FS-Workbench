"""Keep the original restart and health assertion; bound additional cold-start waiting."""
import json,time,urllib.request,subprocess

def extend(base,scope,clock=time.monotonic,sleep=time.sleep,open_url=urllib.request.urlopen,run=subprocess.run):
    original=base.restart_for
    def restart(manifest,admission_fence=None):
        try:return original(manifest,admission_fence)
        except ValueError as error:
            if manifest.get('scope')!=scope or str(error)!='range health failed':raise
        # The original already restarted once; retain its fence and wait for that same process.
        deadline=clock()+25
        while clock()<deadline:
            try:
                with open_url('http://127.0.0.1:8931/health',timeout=1) as response:
                    if json.load(response).get('ok') is True:
                        run(['nginx','-t'],check=True,timeout=20)
                        run(['systemctl','reload','nginx'],check=True,timeout=20)
                        return
            except OSError:pass
            sleep(.1)
        raise ValueError('range health failed after bounded cold-start wait')
    base.restart_for=restart
