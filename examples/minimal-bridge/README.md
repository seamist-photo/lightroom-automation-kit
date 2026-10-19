# Minimal bridge skeleton

Four small files that show the load-bearing parts of a Lightroom plugin bridge:

```
Info.lua                  eager-load flags + the required menu item
Bridge.lua                polling loop, command table, write path
PluginInfoProvider.lua    status panel that never mutates lifecycle
MenuShowStatus.lua        the manual start fallback
```

It speaks a file protocol (`inbox/*.txt` in, `outbox/*.txt` out) on purpose:
zero dependencies, easy to debug by hand, and the failure modes are visible on
disk. A socket transport is faster to respond but adds port ownership, framing
and authentication concerns - see the project docs before going there.

## Install

1. Copy this folder to a file named `ExampleBridge.lrplugin`.
2. Lightroom: *File → Plug-in Manager → Add*.
3. Quit and reopen Lightroom, then use *Library → Plug-in Extras → Example
   Bridge - Show Status* to start it (or press the panel button).

## Try it

```bash
printf 'ping' > /tmp/lrc-bridge/inbox/001.txt
sleep 2 && cat /tmp/lrc-bridge/outbox/001.txt
```

Nothing here touches your catalog until you send `rate`, and that handler is
demonstrating the write-lock pattern, not doing anything useful. Read it, then
write your own command table.
