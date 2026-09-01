import numpy as np

from facechain.face import FaceEncoding, prepare_search_crop


def test_search_crop_is_valid_jpeg_under_provider_limit() -> None:
    image = np.full((1800, 1200, 3), 127, dtype=np.uint8)
    face = np.array([200, 300, 500, 600] + [0] * 11, dtype=np.float32)
    encoding = FaceEncoding(image, np.zeros((1, 128)), face, 1)
    result = prepare_search_crop(encoding)
    assert result.startswith(b"\xff\xd8")
    assert len(result) <= 500_000
