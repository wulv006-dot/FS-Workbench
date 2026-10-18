"""Second release: exact product-order implementation and its container image only."""

SCOPE = "fs-hermes-product-orders-20261018-v1"
SOURCE = "admin_data_tools_20261018/source/admin_product_orders.py"
SOURCE_SHA256 = "a84b372b0f6ab83d29aae815a16e464ef82dae1d06a2e9bb944d6b619676120c"
BACKEND = (
    ("source/hermes/admin_product_orders.py", "/opt/fs-hermes-fc/admin_product_orders.py"),
    ("source/session/admin_product_orders.py", "/opt/fc27-cloud/marketing-session-20261009/admin_product_orders.py"),
    ("source/session/fc27-p2pah-session.service", "/etc/systemd/system/fc27-p2pah-session.service"),
)
CURRENT_IMAGE = "sha256:9f4ce8ee2621e5f044a060926df1968aef66a970ab5c1d6e2c072b1e754a8053"
CURRENT_TAG = "fc27-cloud-session:hermes-generic-data-20261018-v1"
NEW_TAG = "fc27-cloud-session:hermes-product-match-20261018-v1"
UNIT_BEFORE_SHA256 = "09ff0fd88045cbdbc2af52c662b80588c8b5cf728c7a15775199895c55c4e0cc"
SOURCE_BEFORE_SHA256 = "8bee137c1f0b310d4854635afd323bfa0b61692445f0130f4fb723b59eb5633c"
PRIOR_UI_MANIFEST_SHA256 = "d6e04df7b3fce7903e990eac4a0b0760025cfcdd65d5106c54cba043d3bfb628"
