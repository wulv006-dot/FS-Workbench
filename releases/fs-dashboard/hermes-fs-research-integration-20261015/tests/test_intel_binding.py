import importlib.util
from pathlib import Path
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'source'/'report_semantics.py'
spec=importlib.util.spec_from_file_location('intel_binding_semantics',SOURCE)
semantics=importlib.util.module_from_spec(spec)
spec.loader.exec_module(semantics)

URL='https://www.ea.com/games/ea-sports-fc/fc-27/news/future-stars'
OBSERVED='2026-10-15T17:00:00+00:00'
PUBLISHED='2026-10-09T18:00:00+01:00'


class IntelBindingTests(unittest.TestCase):
    def test_markdown_with_read_documents_does_not_claim_no_evidence(self):
        _,_,note=semantics.intelligence({'intel':[]},{'ev_a':{'data':{'documents':[
            dict(source_url=URL,observed_at=OBSERVED,published_at=PUBLISHED)]}}})
        self.assertIn('已实际读取 1 篇',note)
        self.assertNotIn('未取得',note)

    def check(self,stamp=OBSERVED,published='1999-01-01',documents=None):
        if documents is None:documents=[dict(source_url=URL,observed_at=OBSERVED,published_at=PUBLISHED)]
        evidence={'ev_a':{'captured_at':OBSERVED,'data':{'documents':documents}}}
        result={'period':{'start':'2026-10-08','end':'2026-10-14'},'intel':[
            dict(title='Future Stars',url=URL,retrieved_at=stamp,published_at=published,
                 fact='Official announcement',evidence_ids=['ev_a'])]}
        return semantics.intelligence(result,evidence)

    def test_same_document_observation_and_true_publication(self):
        accepted,pending,_=self.check()
        self.assertEqual(len(accepted),1)
        self.assertEqual(pending,[])
        self.assertEqual(accepted[0]['published_at'],PUBLISHED)

    def test_publication_cannot_be_retrieval(self):
        accepted,pending,_=self.check(stamp=PUBLISHED)
        self.assertEqual(accepted,[])
        self.assertEqual(len(pending),1)

    def test_another_document_observation_cannot_be_retrieval(self):
        other_stamp='2026-10-14T17:00:00+00:00'
        accepted,pending,_=self.check(stamp=other_stamp,documents=[
            dict(source_url=URL,observed_at=OBSERVED,published_at=PUBLISHED),
            dict(source_url=URL+'-other',observed_at=other_stamp,published_at=PUBLISHED)])
        self.assertEqual(accepted,[])
        self.assertEqual(len(pending),1)

    def test_unknown_publication_does_not_keep_model_date(self):
        accepted,_,_=self.check(documents=[dict(source_url=URL,observed_at=OBSERVED,published_at=None)])
        self.assertEqual(accepted[0]['published_at'],'未知（官方未提供）')

    def test_legacy_non_document_evidence_still_works(self):
        evidence={'ev_a':{'data':dict(url=URL,retrieved_at=OBSERVED)}}
        result={'period':{'end':'2026-10-14'},'intel':[
            dict(url=URL,retrieved_at=OBSERVED,fact='Legacy projection',evidence_ids=['ev_a'])]}
        accepted,pending,_=semantics.intelligence(result,evidence)
        self.assertEqual(len(accepted),1)
        self.assertEqual(pending,[])

    def test_empty_document_reply_does_not_certify_coverage_url(self):
        evidence={'ev_a':{'captured_at':OBSERVED,'data':{'documents':[],'coverage':{'index_url':URL}}}}
        result={'period':{'end':'2026-10-14'},'intel':[
            dict(url=URL,retrieved_at=OBSERVED,fact='No documents',evidence_ids=['ev_a'])]}
        accepted,pending,_=semantics.intelligence(result,evidence)
        self.assertEqual(accepted,[])
        self.assertEqual(len(pending),1)


if __name__=='__main__':unittest.main()
