"""lrc-kit: practical tooling for Adobe Lightroom Classic automation.

Three independent pieces, deliberately low-dependency:

* ``catalog``  - read a ``.lrcat`` (it is just SQLite) without opening Lightroom.
* ``preflight`` - check Lua plugin code without restarting Lightroom.
* ``color_eval`` - judge a color match numerically instead of by eye.

Design rule shared by all three: every claim must be backed by a number or a
real exit code. "It ran without an error" is not evidence.
"""

__version__ = "0.1.0"

__all__ = ["catalog", "preflight", "color_eval"]
