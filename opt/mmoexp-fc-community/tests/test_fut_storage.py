import tempfile
import unittest
from pathlib import Path
from community import CommunityStore, CommunityError


class FutStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CommunityStore(Path(self.tmp.name)/'test.db', {'owner'})

    def item(self, kind='leak'):
        item = self.store.draft('owner', 'Test FUT content', kind, 'Summary', 'https://example.com/item', 27, 10)
        self.store.approve('owner', item, 11)
        return item

    def test_categories_and_bookmarks_are_separate_and_per_user(self):
        leak = self.item()
        collection = self.item('collection')
        self.assertEqual([r['id'] for r in self.store.feed('leak')], [leak])
        self.assertEqual([r['id'] for r in self.store.feed('collection')], [collection])
        self.store.bookmark('a', leak)
        self.store.bookmark('a', leak)
        self.assertEqual([r['id'] for r in self.store.bookmarks('a')], [leak])
        self.assertEqual(self.store.bookmarks('b'), [])
        self.store.withdraw('owner', leak)
        self.assertEqual(self.store.bookmarks('a'), [])

    def test_unpublished_cannot_be_bookmarked(self):
        item = self.store.draft('owner', 'Draft', 'news', 'Body', 'https://example.com', 27, 10)
        with self.assertRaises(CommunityError):
            self.store.bookmark('a', item)


if __name__ == '__main__':
    unittest.main()
