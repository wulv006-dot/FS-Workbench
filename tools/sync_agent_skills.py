"""Mirror the canonical project skills to Claude Code."""

import argparse
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(".agents/skills")
MIRROR = Path(".claude/skills")
REPAIR = "python tools/sync_agent_skills.py --apply"
MARKDOWN_LINK = re.compile(r"\]\(\s*(<[^>]+>|[^\s)]+)|^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.M)


def read_tree(root, relative, required):
    directory = root / relative
    if directory.parent.is_symlink() or directory.is_symlink():
        raise ValueError(f"skill-sync: symlink at {relative.as_posix()}")
    if not directory.exists() and not required:
        return {}, []
    if not directory.is_dir():
        raise ValueError(f"skill-sync: missing directory {relative.as_posix()}")
    files, directories = {}, []
    for path in sorted(directory.rglob("*")):
        name = path.relative_to(directory)
        if path.is_symlink():
            raise ValueError(f"skill-sync: symlink at {(relative / name).as_posix()}")
        if path.is_file():
            files[name] = path.read_bytes()
        elif path.is_dir():
            directories.append(path)
    return files, directories


def lf_bytes(data):
    # Keep binary assets byte-identical while normalizing UTF-8 skill files.
    if b"\0" not in data:
        try:
            return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        except UnicodeDecodeError:
            pass
    return data


def check_links(root, files):
    problems = []
    for name, data in files.items():
        if name.suffix.lower() != ".md":
            continue
        for match in MARKDOWN_LINK.finditer(data.decode("utf-8-sig")):
            target = next(group for group in match.groups() if group).strip("<>")
            link = urlsplit(target)
            if target.startswith("//") or (link.scheme and len(link.scheme) > 1) or not link.path:
                continue
            raw_path = unquote(link.path)
            path = PurePosixPath(raw_path)
            if (path.is_absolute() or ".." in path.parts or "\\" in raw_path or ":" in raw_path
                    or not (name.parent / path in files or (root / path).exists())):
                problems.append(f"{(SOURCE / name).as_posix()}: {target}")
    if problems:
        raise ValueError("skill-link: use existing paths relative to the skill file or repository root\n"
                         + "\n".join(problems))


def sync(root, apply=False):
    source, _ = read_tree(root, SOURCE, required=True)
    if not any(len(path.parts) == 2 and path.name == "SKILL.md" for path in source):
        raise ValueError("skill-sync: no canonical SKILL.md files")
    check_links(root, source)
    mirror, directories = read_tree(root, MIRROR, required=False)
    expected = {name: lf_bytes(data) for name, data in source.items()}
    missing = sorted(expected.keys() - mirror.keys())
    extra = sorted(mirror.keys() - expected.keys())
    different = sorted(name for name in expected.keys() & mirror.keys() if expected[name] != mirror[name])

    if apply:
        destination = root / MIRROR
        for name in extra:
            (destination / name).unlink()
        for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
        for name in missing + different:
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected[name])
    elif missing or extra or different:
        details = [f"{label}: {', '.join(p.as_posix() for p in paths)}"
                   for label, paths in (("missing from .claude/skills", missing),
                                        ("extra in .claude/skills", extra),
                                        ("content differs", different)) if paths]
        raise ValueError("skill-sync: Claude mirror differs from .agents/skills. Run "
                         + REPAIR + "\n" + "\n".join(details))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Check links and mirror without writing")
    mode.add_argument("--apply", action="store_true", help="Replace the Claude mirror from canonical files")
    args = parser.parse_args()
    try:
        sync(ROOT, apply=args.apply)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print("agent skills: " + ("mirror updated" if args.apply else "links and mirror passed"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
