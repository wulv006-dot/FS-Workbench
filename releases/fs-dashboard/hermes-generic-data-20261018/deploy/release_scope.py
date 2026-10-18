"""Exact prospective backend paths. FROZEN stays false until candidate review completes."""

SCOPE = "fs-hermes-generic-data-20261018-v1"
FROZEN = True

# Reviewed source bytes. A later fix requires a new release scope review.
SOURCE_SHA256 = {
    "fs_hermes_generic_data_20261018/source/controller.py": "cd41e87fceca1e263c90c00323517fab4e145f08c6101086b39297fdc9691631",
    "fs_phase2_data_20261018/source/continuation.py": "dca4eb7a06bc746c4883672136872895c73bdbb002fc2fa8b7109b417b991063",
    "fs_phase2_data_20261018/source/research.py": "49aaa72ffd82d43d8a1fb03f6b19520fd91a726c07f56c0e3da8377381659b59",
    "fs_hermes_generic_data_20261018/source/range_api.py": "7cb5897a0f6a5e346803d7072ae783a4faf789cb2f821ba7bbc972b3082f2118",
    "admin_data_tools_20261018/source/admin_product_orders.py": "8bee137c1f0b310d4854635afd323bfa0b61692445f0130f4fb723b59eb5633c",
    "fs_phase2_data_20261018/source/cohort_paid_source.py": "e711cb9fcaf9c2cdc03af1d28619895dc7f391aaa7f8b4cc3846fca5fc6a3663",
    "fs_phase2_data_20261018/source/cohort_es_source.py": "1ef04fa03035d8afab0a95e5c2462e9e32b8f516d27fef29b32c75a5f0670293",
    "fs_phase2_data_20261018/source/cohort_reader.py": "2fa82bd199f64ec45cb2c30c4298be388092ff4801bf45bec5d51a8c5d048501",
    "fs_hermes_generic_data_20261018/source/p2pah_session_service.py": "147874fbfc6143027f05418699016605474234933b4f1bde56ade29d31f2eb00",
}

# (workspace source, private stage relative path, production target)
BACKEND = (
    ("fs_hermes_generic_data_20261018/source/controller.py", "source/controller.py", "/opt/fs-hermes-fc/controller.py"),
    ("fs_phase2_data_20261018/source/continuation.py", "source/continuation.py", "/opt/fs-hermes-fc/continuation.py"),
    ("fs_phase2_data_20261018/source/research.py", "source/research.py", "/opt/fs-hermes-fc/research.py"),
    ("fs_hermes_generic_data_20261018/source/range_api.py", "source/range_api.py", "/opt/fs-exact-range-20261001/range_api.py"),
    ("admin_data_tools_20261018/source/admin_product_orders.py", "source/hermes/admin_product_orders.py", "/opt/fs-hermes-fc/admin_product_orders.py"),
    ("admin_data_tools_20261018/source/admin_product_orders.py", "source/session/admin_product_orders.py", "/opt/fc27-cloud/marketing-session-20261009/admin_product_orders.py"),
    ("fs_phase2_data_20261018/source/cohort_paid_source.py", "source/hermes/cohort_paid_source.py", "/opt/fs-hermes-fc/cohort_paid_source.py"),
    ("fs_phase2_data_20261018/source/cohort_paid_source.py", "source/session/cohort_paid_source.py", "/opt/fc27-cloud/marketing-session-20261009/cohort_paid_source.py"),
    ("fs_phase2_data_20261018/source/cohort_es_source.py", "source/cohort_es_source.py", "/opt/fs-hermes-fc/cohort_es_source.py"),
    ("fs_phase2_data_20261018/source/cohort_reader.py", "source/cohort_reader.py", "/opt/fs-hermes-fc/cohort_reader.py"),
    ("fs_hermes_generic_data_20261018/source/p2pah_session_service.py", "source/session/p2pah_session_service.py", "/opt/fc27-cloud/marketing-session-20261009/p2pah_session_service.py"),
    ("@generated-session-unit", "source/session/fc27-p2pah-session.service", "/etc/systemd/system/fc27-p2pah-session.service"),
)

NEW_ALLOWED = {
    "/opt/fs-hermes-fc/cohort_paid_source.py",
    "/opt/fc27-cloud/marketing-session-20261009/cohort_paid_source.py",
}
