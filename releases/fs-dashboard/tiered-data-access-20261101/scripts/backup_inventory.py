"""Read-only exact-target metadata inventory. No deletes, SQLite opens or network."""
import argparse
import json
import os
from pathlib import Path

DATES = ('2026-10-29', '2026-10-30')


def inventory(root):
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('inventory_symlink_root')
    result = dict(contract='fs-old-backup-inventory-v1', root=str(root),
                  dependencies='not_verified', recovery_receipts='not_verified',
                  deletion_authorized=False, deletion_performed=False, targets=[])
    for name in DATES:
        target = root/'backups'/name
        if target.is_symlink() or (root/'backups').is_symlink():
            raise ValueError('inventory_symlink_target')
        value = dict(path=str(target), exists=target.is_dir(), files=[], logical_bytes=0,
                     allocated_bytes=None, status='missing')
        if value['exists']:
            allocated, count = 0, 0
            for directory, dirs, files in os.walk(target, followlinks=False):
                for child in dirs+files:
                    if (Path(directory)/child).is_symlink():
                        raise ValueError('inventory_symlink_member')
                for child in files:
                    path=Path(directory)/child; info=path.stat()
                    if not path.is_file(): raise ValueError('inventory_special_file')
                    count+=1
                    if count>1000: raise ValueError('inventory_object_budget')
                    value['files'].append(dict(path=str(path.relative_to(target)),bytes=info.st_size,mtime_ns=info.st_mtime_ns,links=info.st_nlink))
                    value['logical_bytes']+=info.st_size
                    allocated = allocated+info.st_blocks*512 if allocated is not None and hasattr(info,'st_blocks') else None
            value.update(status='metadata_only',file_count=count,allocated_bytes=allocated)
        result['targets'].append(value)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,help='Explicit user analytics root; no implicit production fallback')
    args=parser.parse_args()
    print(json.dumps(inventory(args.root),ensure_ascii=False,indent=2))
