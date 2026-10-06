"""Existing local Linux runtime only; no install/network/server upload/deploy."""
import sys

if __name__ == '__main__':
    if not sys.platform.startswith('linux'):
        raise SystemExit('BLOCKED: existing local Linux runtime required; no remote QA fallback')
    from qa import main
    raise SystemExit(main())
