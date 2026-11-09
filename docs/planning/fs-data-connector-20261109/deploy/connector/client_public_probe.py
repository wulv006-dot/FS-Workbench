"""Credential-free public-entry checks. Does not register clients or authorize a user."""
import http.client
import json
import ssl
import sys

HOST = '47.85.224.112'
ISSUER = 'https://' + HOST + '/connector'
RESOURCE = ISSUER + '/mcp'


def metadata_checks(authorization, protected):
    return dict(issuer=authorization.get('issuer') == ISSUER,
        endpoints=all(authorization.get(name + '_endpoint') == ISSUER + '/oauth/' + path
            for name, path in [('authorization', 'authorize'), ('token', 'token'),
                               ('registration', 'register'), ('revocation', 'revoke')]),
        pkce_s256='S256' in authorization.get('code_challenge_methods_supported', []),
        public_client='none' in authorization.get('token_endpoint_auth_methods_supported', []),
        resource=protected.get('resource') == RESOURCE,
        authorization_server=protected.get('authorization_servers') == [ISSUER],
        read_scope='fs.read' in protected.get('scopes_supported', []))


def request(path, payload=None, timeout=10):
    connection = http.client.HTTPSConnection(HOST, timeout=timeout, context=ssl.create_default_context())
    try:
        headers = {'Accept': 'application/json'}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        connection.request('GET' if payload is None else 'POST', path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError('public_response_too_large')
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError):
            document = None
        return response.status, response.getheader('WWW-Authenticate', ''), document
    finally:
        connection.close()


def main():
    report = dict(tls_verification_required=True, oauth_state_created=False)
    try:
        status, _, authorization = request('/.well-known/oauth-authorization-server/connector')
        report['authorization_metadata_status'] = status
        protected_status, _, protected = request('/.well-known/oauth-protected-resource/connector/mcp')
        report['protected_metadata_status'] = protected_status
        if status != 200 or protected_status != 200:
            return report, False
        report['metadata'] = metadata_checks(authorization, protected)
        status, challenge, _ = request('/connector/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        report.update(unauthenticated_mcp_status=status,
            protected_resource_challenge='resource_metadata="https://' + HOST + '/.well-known/oauth-protected-resource/connector/mcp"' in challenge)
        return report, all(report['metadata'].values()) and status == 401 and report['protected_resource_challenge']
    except ssl.SSLCertVerificationError:
        report['error'] = 'tls_certificate_verification_failed'
    except (OSError, http.client.HTTPException):
        report['error'] = 'public_entry_unavailable'
    except (ValueError, TypeError, AttributeError):
        report['error'] = 'public_metadata_invalid'
    return report, False


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-check']:
        authorization = dict(issuer=ISSUER, authorization_endpoint=ISSUER + '/oauth/authorize',
            token_endpoint=ISSUER + '/oauth/token', registration_endpoint=ISSUER + '/oauth/register',
            revocation_endpoint=ISSUER + '/oauth/revoke', code_challenge_methods_supported=['S256'],
            token_endpoint_auth_methods_supported=['none'])
        protected = dict(resource=RESOURCE, authorization_servers=[ISSUER], scopes_supported=['fs.read'])
        assert all(metadata_checks(authorization, protected).values())
        protected['resource'] = RESOURCE + '/wrong'
        assert metadata_checks(authorization, protected)['resource'] is False
        print(json.dumps(dict(self_check=True, network_requests=0, oauth_state_created=False)))
    else:
        report, ok = main()
        print(json.dumps(report))
        raise SystemExit(0 if ok else 1)
