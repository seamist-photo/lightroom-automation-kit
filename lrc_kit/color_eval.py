"""Judge a color match numerically instead of by eye.

Visual comparison is how people talk about color and how they get it wrong: two
images can look "close" while being 6 dE apart across the highlights, or look
different while being under the perceptual threshold. Every function here
returns numbers, and ``verdict()`` turns them into a band.

Dependencies are intentionally small: ``numpy`` + ``pillow`` for the main path
(``pip install lrc-kit[color]``). ``scikit-image`` is optional and only used for
SSIM when present.

CIEDE2000 is implemented from the CIE specification rather than pulled from a
color library, and is verified against the published Sharma et al. test pairs in
the test suite.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional

__all__ = ["delta_e_ciede2000", "wasserstein_1d", "lab_from_srgb", "zone_report", "evaluate", "measure"]

# Sharma, Wu & Dalal (2005) test pairs: (L1,a1,b1, L2,a2,b2, expected dE00).
# Used by tests/test_color_eval.py; kept here as documentation of correctness.
SHARMA_PAIRS = [
    (50.0000, 2.6772, -79.7751, 50.0000, 0.0000, -82.7485, 2.0425),
    (50.0000, 3.1571, -77.2803, 50.0000, 0.0000, -82.7485, 2.8615),
    (50.0000, 2.8361, -74.0200, 50.0000, 0.0000, -82.7485, 3.4412),
    (50.0000, -1.3802, -84.2814, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -1.1848, -84.8006, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -0.9009, -85.5211, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, 0.0000, 0.0000, 50.0000, -1.0000, 2.0000, 2.3669),
    (50.0000, -1.0000, 2.0000, 50.0000, 0.0000, 0.0000, 2.3669),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0009, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0010, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0011, 7.2195),
]


def _np():
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("color_eval needs numpy: pip install lrc-kit[color]") from exc
    return np


def delta_e_ciede2000(lab1, lab2):
    """CIE delta-E 2000 between two Lab colours (scalar or Nx3 arrays)."""
    np = _np()
    a = np.asarray(lab1, dtype=float)
    b = np.asarray(lab2, dtype=float)
    scalar = a.ndim == 1
    if scalar:
        a = a.reshape(1, 3)
        b = b.reshape(1, 3)

    L1, a1, b1 = a[:, 0], a[:, 1], a[:, 2]
    L2, a2, b2 = b[:, 0], b[:, 1], b[:, 2]

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    Cbar = (C1 + C2) / 2.0
    G = 0.5 * (1.0 - np.sqrt(Cbar**7 / (Cbar**7 + 25.0**7)))
    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2
    C1p = np.hypot(a1p, b1)
    C2p = np.hypot(a2p, b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    # arctan2(0,0) is defined as 0 here, which matches the spec's convention
    h1p = np.where((np.abs(a1p) < 1e-12) & (np.abs(b1) < 1e-12), 0.0, h1p)
    h2p = np.where((np.abs(a2p) < 1e-12) & (np.abs(b2) < 1e-12), 0.0, h2p)

    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dhp = np.where(np.abs(C1p * C2p) < 1e-12, 0.0, dh)
    dhp = np.where(dhp > 180.0, dhp - 360.0, dhp)
    dhp = np.where(dhp < -180.0, dhp + 360.0, dhp)
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2.0))

    Lbarp = (L1 + L2) / 2.0
    Cbarp = (C1p + C2p) / 2.0
    hsum = h1p + h2p
    hbarp = np.where(
        np.abs(C1p * C2p) < 1e-12,
        hsum,
        np.where(
            np.abs(h1p - h2p) <= 180.0,
            hsum / 2.0,
            np.where(hsum < 360.0, (hsum + 360.0) / 2.0, (hsum - 360.0) / 2.0),
        ),
    )

    T = (
        1.0
        - 0.17 * np.cos(np.radians(hbarp - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * hbarp))
        + 0.32 * np.cos(np.radians(3.0 * hbarp + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * hbarp - 63.0))
    )
    dtheta = 30.0 * np.exp(-(((hbarp - 275.0) / 25.0) ** 2))
    Rc = 2.0 * np.sqrt(Cbarp**7 / (Cbarp**7 + 25.0**7))
    Sl = 1.0 + (0.015 * (Lbarp - 50.0) ** 2) / np.sqrt(20.0 + (Lbarp - 50.0) ** 2)
    Sc = 1.0 + 0.045 * Cbarp
    Sh = 1.0 + 0.015 * Cbarp * T
    Rt = -np.sin(np.radians(2.0 * dtheta)) * Rc

    term_l = dLp / Sl
    term_c = dCp / Sc
    term_h = dHp / Sh

    dE = np.sqrt(term_l**2 + term_c**2 + term_h**2 + Rt * term_c * term_h)
    return float(dE[0]) if scalar else dE


def wasserstein_1d(hist_a, hist_b, lo: float, hi: float) -> float:
    """Earth mover's distance between two histograms over [lo, hi].

    Closed form for the 1-D case: the integral of the absolute CDF difference.
    """
    np = _np()
    a = np.asarray(hist_a, dtype=float)
    b = np.asarray(hist_b, dtype=float)
    if a.sum() == 0 or b.sum() == 0:
        return float("nan")
    a = a / a.sum()
    b = b / b.sum()
    xs = np.linspace(lo, hi, len(a))
    cdf = np.cumsum(a - b)
    return float(np.trapezoid(np.abs(cdf), xs))


def _srgb_to_lab(rgb):
    np = _np()
    rgb = np.clip(rgb, 0.0, 1.0)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    M = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = (lin @ M.T) / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def lab_from_srgb(rgb):
    """Lab (D65, 2 deg) from sRGB values in [0,1]. Public wrapper for tests."""
    return _srgb_to_lab(_np().asarray(rgb, dtype=float))


def _load(path: str, maxdim: int = 640):
    np = _np()
    from PIL import Image  # type: ignore

    im = Image.open(path).convert("RGB")
    im.load()
    im.thumbnail((maxdim, maxdim))
    return np.asarray(im).astype(np.float64) / 255.0


def zone_report(lab_a, lab_b) -> Dict[str, Any]:
    """Signed per-zone delta (target minus result) in L*, a*, b*."""
    np = _np()
    L = lab_b[:, 0]
    zones = {"shadow": L < 33, "midtone": (L >= 33) & (L < 66), "highlight": L >= 66}
    dL = lab_b[:, 0] - lab_a[:, 0]
    da = lab_b[:, 1] - lab_a[:, 1]
    db = lab_b[:, 2] - lab_a[:, 2]
    out: Dict[str, Any] = {}
    for name, mask in zones.items():
        if not mask.any():
            continue
        out[name] = {
            "dL": round(float(dL[mask].mean()), 2),
            "da": round(float(da[mask].mean()), 2),
            "db": round(float(db[mask].mean()), 2),
            "hue_shift_deg": round(float(np.degrees(np.arctan2(db[mask].mean(), da[mask].mean())) % 360.0), 1),
            "share_pct": round(float(100.0 * mask.sum() / len(L)), 1),
        }
    return out


def _verdict(mean_de: float) -> str:
    if mean_de < 2:
        return "EXCELLENT (<2 dE: imperceptible)"
    if mean_de < 5:
        return "GOOD (<5 dE: close, small moves left)"
    if mean_de < 10:
        return "FAIR (<10 dE: visible difference)"
    return "POOR (>=10 dE: visibly different color)"


def evaluate(result_path: str, target_path: str, bins: int = 64, maxdim: int = 640) -> Dict[str, Any]:
    """Compare a result image against a target image, numerically."""
    np = _np()
    A = _load(result_path, maxdim)
    B = _load(target_path, maxdim)
    h = min(A.shape[0], B.shape[0])
    w = min(A.shape[1], B.shape[1])
    A, B = A[:h, :w], B[:h, :w]

    labA = _srgb_to_lab(A).reshape(-1, 3)
    labB = _srgb_to_lab(B).reshape(-1, 3)
    dE = delta_e_ciede2000(labA, labB)

    out: Dict[str, Any] = {
        "n_pixels": int(dE.size),
        "dE2000": {
            "mean": round(float(dE.mean()), 3),
            "p50": round(float(np.percentile(dE, 50)), 3),
            "p90": round(float(np.percentile(dE, 90)), 3),
            "p95": round(float(np.percentile(dE, 95)), 3),
            "max": round(float(dE.max()), 3),
            "pct_lt2": round(float(100.0 * (dE < 2).mean()), 1),
            "pct_lt5": round(float(100.0 * (dE < 5).mean()), 1),
            "pct_lt10": round(float(100.0 * (dE < 10).mean()), 1),
        },
    }
    out["verdict"] = _verdict(out["dE2000"]["mean"])

    emd: Dict[str, float] = {}
    for i, name in enumerate(("L", "a", "b")):
        lo, hi = (0.0, 100.0) if i == 0 else (-50.0, 50.0)
        ha, _ = np.histogram(labA[:, i], bins=bins, range=(lo, hi), density=False)
        hb, _ = np.histogram(labB[:, i], bins=bins, range=(lo, hi), density=False)
        emd[name] = round(wasserstein_1d(ha, hb, lo, hi), 4)
    out["hist_emd"] = emd

    try:
        from skimage.metrics import structural_similarity as ssim  # type: ignore

        gA = 0.2126 * A[..., 0] + 0.7152 * A[..., 1] + 0.0722 * A[..., 2]
        gB = 0.2126 * B[..., 0] + 0.7152 * B[..., 1] + 0.0722 * B[..., 2]
        out["ssim_luminance"] = round(float(ssim(gA, gB, data_range=1.0)), 4)
    except ImportError:
        out["ssim_luminance"] = None
        out.setdefault("notes", []).append("SSIM skipped: pip install lrc-kit[ssim]")

    out["zone_delta_target_minus_result"] = zone_report(labA, labB)
    out["chroma_result"] = round(float(np.hypot(labA[:, 1], labA[:, 2]).mean()), 3)
    out["chroma_target"] = round(float(np.hypot(labB[:, 1], labB[:, 2]).mean()), 3)
    out["chroma_delta"] = round(out["chroma_target"] - out["chroma_result"], 3)
    return out


def measure(target_path: str, maxdim: int = 640) -> Dict[str, Any]:
    """Lab statistics of one image, to turn a reference photo into slider hints."""
    np = _np()
    rgb = _load(target_path, maxdim)
    pix = rgb.reshape(-1, 3)
    lab = _srgb_to_lab(rgb).reshape(-1, 3)
    L = np.clip(lab[:, 0], 0.0, 100.0)
    A, B = lab[:, 1], lab[:, 2]

    out: Dict[str, Any] = {
        "L_mean": round(float(L.mean()), 1),
        "L_p5": round(float(np.percentile(L, 5)), 1),
        "L_median": round(float(np.percentile(L, 50)), 1),
        "L_p95": round(float(np.percentile(L, 95)), 1),
        "L_min": round(float(L.min()), 1),
        "L_max": round(float(L.max()), 1),
        # crude first guess at an Exposure2012 move; not a substitute for a test render
        "exposure_bias_ev": round(float((L.mean() - 50.0) / 50.0), 2),
        "chroma_mean": round(float(np.hypot(A, B).mean()), 1),
    }

    def zone(mask) -> Optional[Dict[str, float]]:
        if not mask.any():
            return None
        a_m = float(A[mask].mean())
        b_m = float(B[mask].mean())
        return {
            "a": round(a_m, 1),
            "b": round(b_m, 1),
            "chroma": round(math.hypot(a_m, b_m), 1),
            "hue": round(float(np.degrees(np.arctan2(b_m, a_m)) % 360.0), 1),
            "share_pct": round(float(100.0 * mask.sum() / len(L)), 1),
        }

    out["shadows"] = zone(L < 33)
    out["midtones"] = zone((L >= 33) & (L < 66))
    out["highlights"] = zone(L >= 66)

    # HSL hint: mean saturation per hue band
    mx = pix.max(axis=1)
    mn = pix.min(axis=1)
    v = mx
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    r, g, b = pix[:, 0], pix[:, 1], pix[:, 2]
    hue = np.zeros_like(v)
    d = mx - mn + 1e-6
    m = mx == r
    hue[m] = ((g - b) / d)[m] % 6.0
    m = mx == g
    hue[m] = ((b - r) / d)[m] + 2.0
    m = mx == b
    hue[m] = ((r - g) / d)[m] + 4.0
    hue *= 60.0

    names = ["Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple", "Magenta"]
    bands = [(0, 20), (20, 45), (45, 65), (65, 160), (160, 200), (200, 260), (260, 300), (300, 360)]
    per_hue = []
    for name, (lo, hi) in zip(names, bands):
        mask = (hue >= lo) & (hue < hi)
        per_hue.append(
            {
                "hue": name,
                "mean_sat": round(float(s[mask].mean()), 3) if mask.any() else None,
                "share_pct": round(float(100.0 * mask.sum() / len(hue)), 1),
            }
        )
    out["per_hue"] = per_hue
    return out
