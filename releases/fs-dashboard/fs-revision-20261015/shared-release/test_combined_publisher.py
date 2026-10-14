"""Run account and AI boundary cases against the actual combined publisher."""
import importlib.util
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
publisher=load('combined',HERE/'release_navigation.py')
accounts=load('account_contracts',HERE.parent/'accounts/tests/test_publisher.py')
ai=load('ai_contracts',HERE.parent/'accounts/integration/test_ai_publisher.py')
accounts.publisher=publisher;ai.publisher=publisher
class AccountBoundary(accounts.PublisherTests):pass
class AIBoundary(ai.PublisherTests):pass
if __name__=='__main__':unittest.main()
