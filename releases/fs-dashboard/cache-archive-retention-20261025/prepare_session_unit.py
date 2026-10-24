"""Change only the existing Admin image reference after both images are verified."""
import re

OLD_TAG='fc27-cloud-session:monthly-paid-20261021-v1'
OLD_IMAGE='sha256:205893bef1ed82ffba1c5161972a55172394a7f1b020172a81dd26602a493f81'


def candidate(raw,new_image):
    if re.fullmatch('sha256:[a-f0-9]{64}',new_image) is None or new_image==OLD_IMAGE:
        raise ValueError('archive_session_image_invalid')
    if raw.count(OLD_TAG.encode())!=1:raise ValueError('archive_session_unit_drift')
    return raw.replace(OLD_TAG.encode(),new_image.encode(),1)
