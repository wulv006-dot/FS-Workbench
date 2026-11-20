"""Apply the VIP pagination query budget to the composed Range service source."""
from hashlib import sha256

BASELINE_SHA = '604c242f50e30de5704d2924df0e8e03b3d870026233c833fc4dff9cf73872c9'
TRACKING_GET = (
    b"   try:status,data=CUSTOMER_TRACKING.get(self.headers.get('X-Auth-User'),"
    b"parse_qs(uri.query,keep_blank_values=True,max_num_fields=8));self.reply(status,data)\n"
)


def patch(raw):
    if sha256(raw).hexdigest() != BASELINE_SHA or raw.count(TRACKING_GET) != 1:
        raise ValueError('vip_paging_range_baseline_changed')
    # mode, structure and view plus start, end, as_of, scope, segment and offset.
    return raw.replace(TRACKING_GET, TRACKING_GET.replace(b'max_num_fields=8', b'max_num_fields=9'), 1)
