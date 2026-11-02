"""Settings shared by the tests."""

from __future__ import annotations

import os

from hypothesis import settings

# no time limit per example: a loaded or slow runner (`make test`'s workers, Windows CI on
# Python 3.9) takes longer than Hypothesis's 200 ms, which fails a correct property
settings.register_profile("composeui", settings.get_profile("default"), deadline=None)
# on CI, Hypothesis's own profile: the same examples each run (`derandomize`), without a
# time limit, so that a pull request fails for its change, not for a new random draw
settings.load_profile("ci" if os.environ.get("CI") else "composeui")
