import json
import tempfile
import unittest
from urllib.parse import parse_qs
from unittest.mock import patch
import email_channels as m

class ChannelsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls=[]
        self.result=(200,{"result":True,"statusCode":200,"info":{"emailIdList":["message1"]}})
        def send(*args):
            self.calls.append(args)
            if isinstance(self.result,Exception): raise self.result
            return self.result
        self.service=m.Channels(self.temp.name,send)
        for p in m.PROVIDERS:
            self.service.save(dict(provider=p,region="us",api_user="test",secret="PRIVATE_TEST_KEY",from_email="sender@example.com",from_name="FS",reply_to="reply@example.com",test_email="test@example.com"))
    def request(self,p="aurora",mode="send",id="unique_request_0001"):
        return dict(provider=p,mode=mode,request_id=id,confirm=True)
    def test_secret_never_returned_and_blank_keeps(self):
        self.assertNotIn("PRIVATE_TEST_KEY",json.dumps(self.service.public()))
        self.service.save(dict(provider="aurora",secret="",region="sg"))
        self.assertEqual(self.service.read()["aurora"]["secret"],"PRIVATE_TEST_KEY")
    def test_aurora_payload_and_durable_idempotence(self):
        result=self.service.test(self.request(),"admin")
        self.assertEqual(result["state"],"accepted")
        url,data,headers=self.calls[0]
        self.assertEqual(url,"https://api-us.aurorasendcloud.com/api/mail/send")
        self.assertEqual(parse_qs(data.decode())["to"],["test@example.com"])
        again=m.Channels(self.temp.name,lambda *a:self.fail("duplicate send"))
        self.assertTrue(again.test(self.request(),"admin")["replayed"])
    def test_timeout_blocks_new_id(self):
        self.result=TimeoutError("PRIVATE_TEST_KEY")
        self.assertEqual(self.service.test(self.request(),"admin")["state"],"unknown")
        with self.assertRaises(m.Invalid):self.service.test(self.request(id="unique_request_0002"),"admin")
        self.assertEqual(len(self.calls),1)
        self.assertNotIn("PRIVATE_TEST_KEY",json.dumps(self.service.records()))
    def test_mamba_documented_camel_case_batch(self):
        self.result=(200,{"status":"all_success","batchId":"batch1","total_accepted_recipients":1})
        self.assertEqual(self.service.test(self.request("mamba"),"admin")["state"],"accepted")
        payload=json.loads(self.calls[0][1])
        self.assertEqual(payload["total"],1)
        self.assertEqual(payload["emails"],"test@example.com")
    def test_mamba_partial_not_success(self):
        self.result=(200,{"status":"part_success","batch_id":"b","total_accepted_recipients":1})
        self.assertEqual(self.service.test(self.request("mamba"),"admin")["state"],"unknown")
    def test_validate_not_delivered(self):
        self.assertEqual(self.service.test(self.request(mode="validate"),"admin")["state"],"validated")
        self.assertEqual(parse_qs(self.calls[0][1].decode())["sandboxMode"],["validate"])
        with self.assertRaises(m.Invalid):self.service.test(self.request("mamba",mode="validate"),"admin")
    def test_duplicate_provider_reply_is_unknown(self):
        self.result=(200,{"result":False,"statusCode":40000})
        self.assertEqual(self.service.test(self.request(),"admin")["state"],"unknown")
    def test_invalid_region_and_multiple_recipients(self):
        for body in [dict(provider="aurora",region="http://localhost"),dict(provider="mamba",test_email="one@example.com,two@example.com")]:
            with self.assertRaises(m.Invalid):self.service.save(body)
    def test_requires_confirm(self):
        body=self.request();body["confirm"]=False
        with self.assertRaises(m.Invalid):self.service.test(body,"admin")
        self.assertEqual(self.calls,[])
    def test_live_role_and_csrf(self):
        conn=unittest.mock.MagicMock();response=conn.getresponse.return_value;response.status=200
        response.getheader.side_effect=lambda key:{"X-Auth-Role":"readonly","X-Auth-User":"reader"}.get(key)
        with patch.object(m.http.client,"HTTPConnection",return_value=conn):
            self.assertIsNone(m.authorize({},"GET","/api/email/config"))
            response.getheader.side_effect=lambda key:{"X-Auth-Role":"admin","X-Auth-User":"admin"}.get(key)
            self.assertIsNone(m.authorize({},"POST","/api/email/config"))
            self.assertIsNone(m.authorize({"X-FS-Email-Request":"1","Origin":"https://evil.example","Host":"fs.example"},"POST","/api/email/config"))
            self.assertEqual(m.authorize({"X-FS-Email-Request":"1","Origin":"https://fs.example","Host":"fs.example"},"POST","/api/email/config"),"admin")

if __name__=="__main__":unittest.main()
