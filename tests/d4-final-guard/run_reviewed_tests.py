"""Stage exact reviewed tests in a private temporary tree; never run app/server/CLI."""
from pathlib import Path
import argparse,hashlib,importlib.util,shutil,sys,tempfile,unittest
sys.dont_write_bytecode=True
REPO=Path(__file__).resolve().parents[2]
SOURCE_FILES=[('aion2_watch.py', '18997bf016b45c8266fb23404df4123ea94ceff90f068830704c971982f2e475'), ('aion2_xlsx.py', 'f8fe06fd3cf8b7a2a52bb9d5d1c0e3e757984372201178a7e3eb56bcbbc5d824'), ('align_all.py', '0ebcaf58740f4ccf9df90ced6442369abe03a837310ed5c0521d170f85df8ad2'), ('app.py', '655503d5b352e22d26cf256c978c88c330f13c0c4570138b8ad5b57a26923bb7'), ('apply_price.py', 'b15a78208528fb91677a8fc7a4afc510d242de1887a53256edbda8ca57ba5fec'), ('build_dashboard.py', 'e5c30f581716d52994d078ed21dc8a34e203d5f0c28d8f5af5dfd676c4fb6107'), ('core_dd373_cost.py', '8a77cb47b97c4d55016fdcafaf695b84142ab8366cddf9be56536dbc22a10476'), ('core_eld.py', 'c1242f2c6bee947fd6d1520ba266986b7bae30fc293d84a4fff37b993ea9395a'), ('core_front.py', '7e3c886f92e8cb7cc4fe7571c314d98204c6860c208dea96c930a2a003799f53'), ('core_g2g.py', '5af4f076ead321d077ec1679000bf74aa1928910b22557a0886ffef5e6681586'), ('core_gold.py', 'd588f4da02d3a77f3ea76de9839725c0fc14c579b59941c29dbd6803db441947'), ('core_iggm.py', '81f24223009c84abf8309a98b3e97712c30cee214d2b6f14d7b7e168037ebf48'), ('core_multi.py', 'd752468e8a35c75165fcafb19a64e2bcf2200f666e770d3f0f17a0388c9cc23d'), ('core_p2pah.py', '5811c9c8eab58bbf94e3341f72a4c7b06ae088be0989f768c4a3b277f50ab29b'), ('core_qd.py', 'eb416e0171b1e17de6e8f77dc3a445258b92f6e1a08566e27a4e5ebdfde40545'), ('dingtalk_push.py', '72a11b0783e6c101a14742e67805c1a9209e1381ed2ab2b75129652baf7f5d4c'), ('dispatch_align.py', 'eba500627426fd9f8eb8b551789b8c0cb510e452734524bbea04411d08925587'), ('engine.py', '71762e037a2ce1c5dae5d7c8e02738fa8c3b93d209cfc92b39d24ee70f7b7340'), ('gates.py', 'c68c056f6b6522a0bff3762083e8170a14b3c055ef56a1a3bbdc06295ef8326c'), ('gold_numeric_guard.py', '6498e8dd08e491dd0f8f5c4add3d607a98b979568c235c7a154f3641b77316b9'), ('poe2_align.py', '75c8c2e6254f5b4643478554c5992e85603fda2a1e69ec3c39584224ff3ba420'), ('shelf_check.py', '5e5dde35fb2399eee848778b82ace3199e08f49558b03e00d0febc5fdbbe1868'), ('shelf_notify.py', '2a4d305db304524dd3c37b4f758f27449d3b10ad8a9b4a109a04b0ba070f7eb0'), ('shelf_patch.py', '7fd04726a5bb97becf04121808207737673a9b22a8ff5421dafe8bab387b0e9d'), ('srv_exec.py', '1c74a40a4b053cc8e33a43610c788743c62298444e4a5942fd179b7c1087e4a6'), ('store.py', 'b5f3fcc9899ca805ea6fd3dce162265377ead67f73bbeb930aee89bf05293e77'), ('switch_pricing_mode.py', '783c33500ad8b883905c253e7ed7eebdec47113ec41ec3b01e1030ed90239fff'), ('templates/index.html', 'cb6a6e49e08c62f610f081e6a1e01012c5c2bfa2aa25360b579f5fc13dacf8dc'), ('tracker.py', '38fadf1983897dd52924bf1556c3507c759c5a6d2eafc7f846eedf2fe94d2fa9')]
TEST_FILES=[('test_isolated.py', '2790db595a5729761fbc9e9ddceb81e25efe458cf9647a356eedde68ae29c45e'), ('test_closure.py', 'd55992b1e0a34e5cd92234e4801cbc69b2a0354a1484749297c2ad934ce1d366')]
ap=argparse.ArgumentParser();ap.add_argument('--recorded-writer',type=Path,help='Optional existing sanitized local audit fixture; never exported or copied')
args=ap.parse_args()
if args.recorded_writer:
    assert args.recorded_writer.is_file(),'Missing external sanitized fixture; no production download'
    assert hashlib.sha256(args.recorded_writer.read_bytes()).hexdigest()=='5765f759bf4e8e2e8ca27856270e01aef2228c8e11bc6dfcaa4b8ec35ffbceec','External fixture SHA drift; stop'
with tempfile.TemporaryDirectory(prefix='fs-d4-final-test-') as task:
    root=Path(task);view=root/'d4_final_guard_review_20261006';view.mkdir()
    for rel,expected in SOURCE_FILES:
        src=REPO/'opt/d4follow'/rel;assert hashlib.sha256(src.read_bytes()).hexdigest()==expected,'Reviewed source drift: '+rel
        dest=view/'candidate/opt/d4follow'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    for name,expected in TEST_FILES:
        src=Path(__file__).parent/name;assert hashlib.sha256(src.read_bytes()).hexdigest()==expected,'Reviewed test drift: '+name
        shutil.copyfile(src,view/name)
    def module(name,filename):
        spec=importlib.util.spec_from_file_location(name,view/filename);obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
    if args.recorded_writer:
        c=module('reviewed_closure','test_closure.py');c.WRITER_PATH=args.recorded_writer.resolve()
        suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c.h.Synthetic),unittest.defaultTestLoader.loadTestsFromTestCase(c.Closure)])
    else:
        h=module('reviewed_isolated','test_isolated.py');suite=unittest.defaultTestLoader.loadTestsFromTestCase(h.Synthetic)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
