import sys

import pytest

from parseo import validate_schema


pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win") and sys.version_info < (3, 12),
    reason="Schema round-trip validation is unstable on Windows Python < 3.12.",
)


def test_schema_examples_round_trip():
    validate_schema(verbose=True)

