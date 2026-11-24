"""Run the installed Windows quote API or readback task without a console."""

import os
from pathlib import Path
import runpy
import sys


def main():
    if sys.argv[1:2] not in (['quote-api'], ['readback']):
        raise SystemExit('expected quote-api or readback')
    role = sys.argv.pop(1)
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    # pythonw provides no console streams. The legacy HTTP handler writes an
    # access line to stderr inside send_response(), before sending the headers.
    for name in ('stdout', 'stderr'):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
    if role == 'quote-api':
        runpy.run_module('fc_collection.local_quote_api', run_name='__main__', alter_sys=True)
    else:
        runpy.run_path(str(root / 'entry.py'), run_name='__main__')


if __name__ == '__main__':
    main()
