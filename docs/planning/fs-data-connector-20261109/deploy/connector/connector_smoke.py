"""Anonymous public checks; local mode is explicitly not a public TLS acceptance."""
import argparse
import http.client
import importlib.util
import json
from pathlib import Path
import ssl

spec=importlib.util.spec_from_file_location('public_probe',Path(__file__).with_name('client_public_probe.py'))
public=importlib.util.module_from_spec(spec);spec.loader.exec_module(public)


def probe(local_port=None):
    def request(path,payload=None):
        conn=(http.client.HTTPConnection('127.0.0.1',local_port,timeout=10) if local_port else
              http.client.HTTPSConnection(public.HOST,timeout=10,context=ssl.create_default_context()))
        try:
            headers={'Host':public.HOST,'Accept':'application/json'}
            body=None
            if payload is not None:
                body=json.dumps(payload).encode();headers['Content-Type']='application/json'
            conn.request('GET' if body is None else 'POST',path,body=body,headers=headers)
            response=conn.getresponse();raw=response.read(131073)
            if len(raw)>131072:raise ValueError('response_too_large')
            return response.status,dict(response.getheaders()),raw
        finally:conn.close()
    a=request('/.well-known/oauth-authorization-server/connector')
    p=request('/.well-known/oauth-protected-resource/connector/mcp')
    assert a[0]==p[0]==200
    checks=public.metadata_checks(json.loads(a[2]),json.loads(p[2]))
    assert all(checks.values()),'metadata_contract'
    m=request('/connector/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/list'})
    h={k.lower():v for k,v in m[1].items()}
    assert m[0]==401 and 'resource_metadata="'+public.ISSUER.split('/connector')[0]+'/.well-known/oauth-protected-resource/connector/mcp"' in h.get('www-authenticate','')
    assets={}
    for name,mime in [('fs-tokens.css','text/css'),('fs-ui.css','text/css'),('fs-theme.js','text/javascript'),('consent.css','text/css')]:
        item=request('/connector/assets/'+name);headers={k.lower():v for k,v in item[1].items()}
        assert item[0]==200 and mime in headers.get('content-type','') and headers.get('x-content-type-options')=='nosniff',name
        assets[name]=item[0]
    error=request('/connector/oauth/authorize');headers={k.lower():v for k,v in error[1].items()}
    assert error[0]==400 and "form-action 'self'" in headers.get('content-security-policy','')
    assert request('/connector/not-registered')[0]==404
    result={'local_image_test':bool(local_port),'tls_verified':not bool(local_port),'metadata':checks,
            'unauthenticated_mcp_status':m[0],'assets':assets,'error_csp':True,'unknown_route_status':404,'oauth_state_created':False}
    if not local_port:
        dashboard=request('/dashboard/')
        assert dashboard[0]==302,'original_dashboard_login_redirect'
        result['dashboard_status']=dashboard[0]
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--local-port',type=int);args=parser.parse_args()
    print(json.dumps(probe(args.local_port),ensure_ascii=False))
