"""CIEDE2000 is verified against the published Sharma test pairs.

If these numbers do not match, the implementation is wrong - that is the whole
point of using external reference data instead of self-generated expectations.
"""

from __future__ import annotations

import unittest

from lrc_kit.color_eval import SHARMA_PAIRS

try:
    import numpy as np

    HAVE_NUMPY = True
except ImportError:  # pragma: no cover
    HAVE_NUMPY = False


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed (pip install lrc-kit[color])")
class DeltaETests(unittest.TestCase):
    def test_sharma_reference_pairs(self):
        from lrc_kit.color_eval import delta_e_ciede2000

        for L1, a1, b1, L2, a2, b2, expected in SHARMA_PAIRS:
            got = delta_e_ciede2000(np.array([L1, a1, b1]), np.array([L2, a2, b2]))
            self.assertAlmostEqual(
                got, expected, places=3, msg=f"pair {(L1,a1,b1)} vs {(L2,a2,b2)}"
            )

    def test_identity_is_zero(self):
        from lrc_kit.color_eval import delta_e_ciede2000

        lab = np.array([50.0, 12.0, -7.0])
        self.assertAlmostEqual(delta_e_ciede2000(lab, lab), 0.0, places=6)

    def test_symmetry(self):
        from lrc_kit.color_eval import delta_e_ciede2000

        a = np.array([61.0, 20.0, -30.0])
        b = np.array([44.0, -12.0, 8.0])
        self.assertAlmostEqual(delta_e_ciede2000(a, b), delta_e_ciede2000(b, a), places=6)

    def test_vectorised_matches_scalar(self):
        from lrc_kit.color_eval import delta_e_ciede2000

        lab1 = np.array([[50.0, 2.6772, -79.7751], [61.0, 20.0, -30.0]])
        lab2 = np.array([[50.0, 0.0, -82.7485], [44.0, -12.0, 8.0]])
        vec = delta_e_ciede2000(lab1, lab2)
        sca = [delta_e_ciede2000(lab1[i], lab2[i]) for i in range(2)]
        np.testing.assert_allclose(vec, sca, rtol=1e-9)


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class DistanceTests(unittest.TestCase):
    def test_wasserstein_identical_is_zero(self):
        from lrc_kit.color_eval import wasserstein_1d

        hist = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
        self.assertAlmostEqual(wasserstein_1d(hist, hist, 0, 100), 0.0)

    def test_wasserstein_shifted_histogram(self):
        from lrc_kit.color_eval import wasserstein_1d

        a = np.zeros(50)
        b = np.zeros(50)
        a[10] = 1.0
        b[20] = 1.0
        # one unit weight moved 10 bins across a 0..100 span = 20 units of distance
        self.assertGreater(wasserstein_1d(a, b, 0, 100), 0.0)

    def test_lab_from_srgb_white(self):
        from lrc_kit.color_eval import lab_from_srgb

        lab = lab_from_srgb(np.array([[[1.0, 1.0, 1.0]]]))
        self.assertAlmostEqual(float(lab[0, 0, 0]), 100.0, places=1)


if __name__ == "__main__":
    unittest.main()
