"""Local-only source-bound portal demonstration. Explicit main starts the server."""
import argparse
from contextlib import nullcontext
import tempfile
from integrated_server import Environment, create_server, SYNTHETIC_PASSWORD
from native_integration import policy


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--sandbox');args=parser.parse_args()
    context=nullcontext(args.sandbox) if args.sandbox else tempfile.TemporaryDirectory(prefix='fs-registration-')
    with context as root:
        env=Environment(root);server=create_server(env,args.port)
        print(f'Local synthetic preview: http://127.0.0.1:{server.server_port}/__auth/access/',flush=True)
        print('Synthetic native admin from policy: '+sorted(policy.ADMINS)[0]+' / '+SYNTHETIC_PASSWORD,flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close();env.close()


if __name__=='__main__': main()
