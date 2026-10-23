"""Three display refinements through the same checked publisher; original receipts retained."""
import json
from pathlib import Path
import deploy

deploy.TARGETS={k:v for k,v in deploy.TARGETS.items() if k in
                ('reference_observer_view.py','fc27-coins.html','fc27-reference-observer.js')}
deploy.OPERATION='fc-reference-observer-ui-20261023-v2'
deploy.RECEIPT_NAME='ui-recovery-final.json'
if __name__=='__main__':print(json.dumps(deploy.main('--apply' in __import__('sys').argv)))
