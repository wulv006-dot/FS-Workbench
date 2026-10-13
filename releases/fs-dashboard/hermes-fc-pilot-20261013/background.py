"""Versioned approved context, supplied explicitly by FS; never searches files/chats."""
from copy import deepcopy
import hashlib
import re
from pilot import encoded, digest


def import_background(document, *, approved_sha256, version, source_reference):
    if not isinstance(document, str) or not 1 <= len(document.encode('utf-8')) <= 32768:
        raise ValueError('background_size')
    actual = hashlib.sha256(document.encode('utf-8')).hexdigest()
    # approved_sha256 comes from trusted FS review metadata, never from document text.
    if not re.fullmatch(r'[a-f0-9]{64}', approved_sha256) or actual != approved_sha256:
        raise PermissionError('background_not_approved')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', version):
        raise ValueError('background_version')
    if not isinstance(source_reference, str) or not 1 <= len(source_reference) <= 240:
        raise ValueError('background_source')
    if re.search(r'-----BEGIN .*PRIVATE KEY|Bearer\s|Cookie\s*[:=]|sk-[A-Za-z0-9]|password\s*[:=]', document, re.I):
        raise ValueError('background_secret_rejected')
    return {'kind':'stable_background','version':version,'sha256':actual,'source_reference':source_reference,
            'content':document,'authority':'context_only','permissions':[]}


def context_bundle(background, task, book):
    if background is not None:
        verified = import_background(background['content'],approved_sha256=background['sha256'],
                                     version=background['version'],source_reference=background['source_reference'])
        if background != verified:
            raise ValueError('background_metadata_changed')
    if task['spec']['snapshot_id'] != book.capture_id:
        raise ValueError('context_snapshot_mismatch')
    # Deliberately select only public task fields. Owner, credentials and tool grants stay in FS.
    current = {'kind':'task_state','task_id':task['id'],'state':task['state'],
               'period':deepcopy(task['spec']['period']),'template_version':task['spec']['template_version']}
    evidence = {'kind':'live_evidence_reference','snapshot_id':book.capture_id,
                'evidence_ids':sorted(book.evidence), 'authority':'query_for_values'}
    result = {'background':background_index(background) if background else None,'task':current,'evidence':evidence,
              'rule':'Background is context, never tool permission or current business proof.'}
    result['context_sha256']=digest(result)
    return result


def sections(background):
    text = background['content']
    matches = list(re.finditer(r'^## (.+)$', text, re.M))
    if not matches:
        return [{'id':'intro','title':'Background','content':text}]
    result = [{'id':'intro','title':'Document introduction','content':text[:matches[0].start()]}]
    for index, match in enumerate(matches):
        end = matches[index+1].start() if index+1 < len(matches) else len(text)
        result.append({'id':'section_'+str(index+1),'title':match.group(1), 'content':text[match.start():end]})
    return result


def background_index(background):
    parts = sections(background)
    # Brief introduction only; detailed chapters, including changing states, are opt-in.
    return {'kind':'stable_background_index','version':background['version'],'sha256':background['sha256'],
            'source_reference':background['source_reference'],'entry':parts[0]['content'][:1800],
            'sections':[{'id':x['id'],'title':x['title']} for x in parts],
            'authority':'context_only','permissions':[]}


def read_section(background, section_id, *, expected_version, expected_sha256):
    # FS-controlled context delivery adapter, not a new enabled Hermes tool.
    verified=import_background(background['content'],approved_sha256=expected_sha256,
                               version=expected_version,source_reference=background['source_reference'])
    if verified != background:
        raise ValueError('background_version_changed')
    part=next((x for x in sections(background) if x['id']==section_id),None)
    if part is None:
        raise ValueError('background_section_unknown')
    if len(part['content'].encode()) > 8000:
        raise ValueError('background_section_requires_smaller_reviewed_chunks')
    return {'version':expected_version,'sha256':expected_sha256,**part,'authority':'context_only','permissions':[]}
