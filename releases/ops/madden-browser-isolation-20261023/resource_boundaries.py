"""Add resource ceilings to existing launchers, preserving their other arguments."""
import ast
import re


def unit(source, gib):
    pattern=r'(?m)^(ExecStart=\S*docker\s+run)(?=\s)'
    if len(re.findall(pattern,source))!=1 or '--memory' in source:
        raise ValueError('one_original_docker_launcher_required')
    return re.sub(pattern,lambda m:m[1]+f' --memory={gib}g --memory-swap={gib}g',source)


def rpg(source):
    marker='cmd = [DOCKER, "run", "--rm",'
    if source.count(marker)!=2 or '"--memory"' in source:
        raise ValueError('two_original_rpg_launchers_required')
    extra=' "--init", "--memory", "2g", "--memory-swap", "2g",'
    changed=source.replace(marker,marker+extra)
    ast.parse(changed)
    if changed.replace(marker+extra,marker)!=source:
        raise ValueError('unrelated_source_changed')
    return changed
