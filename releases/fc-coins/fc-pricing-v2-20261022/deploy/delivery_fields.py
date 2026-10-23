"""Retain original delivery evidence through the existing locked publisher."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fc_v2_existing_publisher', HERE / 'fc_v2_release_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
adapter.HERE = HERE
adapter.SCOPE = 'fc-delivery-fields-20261023'
adapter.TARGETS = {'source/channel_cost_source.py': '/opt/fs-hermes-fc/channel_cost_source.py'}
adapter.NEW = frozenset()
adapter.RESTART_FC = False


def load_base():
    return adapter.load_base()


if __name__ == '__main__':
    load_base().main()
