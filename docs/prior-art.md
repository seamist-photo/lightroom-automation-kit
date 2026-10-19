# Prior art: what else exists for driving Lightroom

Measured **2026-10-19** via the GitHub and npm APIs. Numbers age fast; the
structure does not.

| project | stars | license | last push | npm downloads/week | verdict |
|---|---|---|---|---|---|
| `Automaat/lightroom-mcp` | 145 | MIT | 2026-10-19 | 1,688 | the de-facto standard, actively developed |
| `drshy-org/lightroom-py` | 3 | MIT | 2026-09-05 | - | broad but effectively unmaintained |
| `varunkumar/lightroom-mcp` | 7 | none | 2026-04-29 | - | no license = not usable commercially |

Also relevant: Adobe's own `remote_control_socket` plugin sample ships with the
Lightroom SDK and is the origin of the `LrSocket` pattern that mature
implementations use.

## What the numbers say versus what they look like

Star counts on this topic are misleading in both directions. Two checks that
actually distinguish "used" from "applauded":

- **npm weekly downloads** for the published package. 145 stars with 1,688
  downloads a week means people run it in real work; 3 stars with no package
  means the README claims capabilities nobody has exercised.
- **Release cadence**. A project shipping several versions a month is being
  maintained; one that stopped two months ago is a snapshot.

The genre also attracts a long tail of near-empty clones - more than a dozen
zero-star repositories re-implementing the same bridge. Treat that as noise, not
as an ecosystem.

## Choosing an approach

- **You want a working integration today**: use `Automaat/lightroom-mcp`. It is
  MIT, cross-platform, and its Lua plugin covers the parts that are hard to get
  right (execution contexts, write locks, port ownership).
- **You want to understand *why* the hard parts are hard**: read
  `plugin-loading-and-execution-contexts.md` here. The code shows what works;
  the reason it has to be that way is what saves you days.
- **You mainly need bulk data or bulk settings**: skip the bridge entirely. Read
  the catalog read-only (`catalog-sqlite.md`) and write `.xmp` sidecars
  (`xmp-and-profiles.md`). No plugin, no server, no open Lightroom.
- **You need to drive the GUI itself**: do not. Screen automation against a
  modal-heavy application is the least reliable option available, and every
  problem it solves is better solved further down the stack.

## On copying code

The projects above are MIT. Copying is legally fine with attribution. Copying
*blind* is not: the interesting bugs in this space are all ordering and context
bugs that look like style choices in a diff. Read the comments explaining the
order, or you will re-discover them one user complaint at a time.
