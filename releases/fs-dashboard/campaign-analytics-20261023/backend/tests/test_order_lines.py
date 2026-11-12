import threading
import unittest

from campaign_backend.core import ContractError
from campaign_backend.order_lines import OrderLineReader

SN = 'D202611100000000001'
PATH = '/order/admin_order/look/id/123.html'


def listing(sn=SN, extra=''):
    cells = [''] * 13
    cells[2] = 'www.mmoexp.com ' + sn
    cells[3] = 'FC 27 PC'
    cells[12] = '<a onclick="openPage(\'' + PATH + '\')">View</a>'
    return '<input name="sn" value="' + SN + '"><table><thead><tr><th>ID</th></tr></thead><tr>' + ''.join('<td>' + x + '</td>' for x in cells) + '</tr></table>' + extra


def detail(qty='1', twice=False):
    item = '<tr class="jq-each-cg" data-gid="1322" data-aid="21946" data-cid="2" data-pid="6530400" data-qty="' + qty + '" data-used="0" data-unit="" data-currency="USD"><td class="col-product-cell"><div class="product-title-wrap">[6530400] Players - Example card</div></td></tr>'
    return '<p>' + SN + '</p><table>' + item * (2 if twice else 1) + '</table>'


class Session:
    def __init__(self, page=None, item=None):
        self.page = listing() if page is None else page
        self.item = detail() if item is None else item
        self.calls = []

    def get_order(self, path, **params):
        self.calls.append((path, params))
        return 200, self.page if len(self.calls) == 1 else self.item


class OrderLinesTest(unittest.TestCase):
    def test_exact_order_native_quantity_and_identity_keep_duplicate_sku_lines(self):
        s = Session(item=detail(twice=True))
        lines = OrderLineReader(s).read(SN)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], dict(game_id='1322', category_id='2', product_id='6530400', attribute_id='21946', platform='pc', quantity='1', unit='item', title='Players - Example card'))
        self.assertNotIn(SN, str(lines))
        self.assertEqual(s.calls[0][1]['sn'], SN)
        self.assertEqual(s.calls[0][1]['status'], 'all')
        self.assertEqual(s.calls[1][0], PATH)

    def test_missing_mismatched_login_and_incomplete_source_are_not_zero(self):
        for page, item in [(listing('DIFFERENT'), detail()), (listing(), detail().replace(SN, SN + 'x')), (listing(), '<input name="password">'), (listing(), '<p>' + SN + '</p>'), (listing(extra='<div class="pagination"><a href="?page=2">2</a></div>'), detail())]:
            with self.subTest(page=page[:20], item=item[:20]), self.assertRaises(ContractError):
                OrderLineReader(Session(page, item)).read(SN)
        for qty in ('', 'NaN', '-1', '0', '.5', '9007199254740992'):
            with self.subTest(qty=qty), self.assertRaises(ContractError):
                OrderLineReader(Session(item=detail(qty))).read(SN)

    def test_product_name_excludes_other_cell_text_and_rejects_unsupported_length(self):
        body = detail().replace('</div>', '</div><p>Unrelated cell note</p>')
        self.assertEqual(OrderLineReader(Session(item=body)).read(SN)[0]['title'], 'Players - Example card')
        with self.assertRaises(ContractError):
            OrderLineReader(Session(item=detail().replace('Example card', 'x' * 241))).read(SN)

    def test_deadline_does_not_queue_another_read_or_start_detail_late(self):
        entered, release = threading.Event(), threading.Event()
        class Slow(Session):
            def get_order(self, path, **params):
                entered.set()
                release.wait(1)
                return super().get_order(path, **params)
        s = Slow()
        reader = OrderLineReader(s)
        try:
            with self.assertRaises(TimeoutError): reader.read(SN, timeout=.01)
            self.assertTrue(entered.is_set())
            with self.assertRaises(TimeoutError): reader.read(SN, timeout=.01)
        finally:
            release.set()
        self.assertLessEqual(len(s.calls), 1)


if __name__ == '__main__':
    unittest.main()
