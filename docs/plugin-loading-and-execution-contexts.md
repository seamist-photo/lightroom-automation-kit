# Lightroom plugin loading and execution contexts

Everything below was verified on **Lightroom Classic 15.x on Windows**, from the
plugin side: `Info.lua`, `LrInitPlugin`, `LrPluginInfoProvider`, file/socket
callbacks. If your plugin "is installed and running" but does nothing, this is
the page you want.

## 1. Plugins are loaded lazily, and the manager lies to you

Open *File → Plug-in Manager* and a working plugin shows **"Installed and
running"**. That status does **not** mean your `LrInitPlugin` script has run.

Lightroom defers plugin initialisation until the plugin is first *used* - a menu
item clicked, a panel rendered, an export filter invoked. Until then `Init.lua`
never executes. Symptoms look like a broken plugin: no log lines, no files
written, no error anywhere.

Two things control this:

```lua
-- Info.lua
LrPluginInfoProvider = 'PluginInfoProvider.lua',
LrInitPlugin = 'PluginInit.lua',
LrForceInitPlugin = true,          -- ask for eager load at startup
LrLibraryMenuItems = {             -- REQUIRED for LrForceInitPlugin to work
  { title = "My Plugin - Show Status", file = "MenuShowStatus.lua" },
},
```

`LrForceInitPlugin = true` is only honoured when the plugin also exposes at
least one menu item. This is the pattern Adobe's own `remote_control_socket`
sample uses. A plugin with `LrForceInitPlugin` and no menu item is still lazy.

**Even with all of that, expect the first launch after installing to need one
manual nudge.** Every mature implementation we compared - socket based and
file based alike - ends up telling users to open Plug-in Manager and press a
start button once. Design for that instead of pretending it does not happen:
put a visible status/start control in your info panel, and make it idempotent.

## 2. Three execution contexts, three different rules

This is the part that costs days if you guess. The same call that works in one
context throws in another.

### (a) Init script context - dies when the script returns

`LrInitPlugin` runs in a context that is torn down as soon as the script
returns. Anything asynchronous started with a bare `LrTasks.startAsyncTask`
inside it is **cancelled mid-flight**, often before its first real statement.

```lua
-- WRONG inside Init.lua: the task is cancelled when the init script returns
LrTasks.startAsyncTask(function()
  LrTasks.sleep(0.5)
  startServer()          -- frequently never runs
end)

-- RIGHT: a fresh context that outlives the init script
LrFunctionContext.postAsyncTaskWithContext("MyPluginAutoStart", function()
  LrTasks.sleep(0.5)     -- let a previous instance release the port
  local ok, err = LrTasks.pcall(startServer)
  if not ok then logError("auto-start failed: " .. tostring(err)) end
end)
```

Observed failure mode when you get this wrong: the server is simply not running
after launch, and nothing is written to the log - because the task was cancelled
and the error path never executed.

### (b) Panel / info-provider context - runs on every render

The module named by `LrPluginInfoProvider` is re-evaluated **every time the
Plug-in Manager panel is drawn**. Put any teardown or "reset" logic in its module
body and opening the manager quietly kills your running server.

Rule: the info provider renders state, it never mutates lifecycle. Do resets in
the init script instead, where they run on load and on "Reload plug-in" but not
on panel render.

### (c) Callback context - cannot yield, cannot take a write lock

File-watch and socket callbacks are invoked from C. Inside them you may parse,
validate and authenticate. You may **not** call `catalog:withWriteAccessDo`,
`photo:applyDevelopSettings`, or anything else that yields - the sandbox rejects
it (`Yielding is not allowed within a C or metamethod call`).

The fix is one line: hand the work to a task.

```lua
local request = parseAndAuthorize(message)   -- pure computation, stays here
if request then
  LrTasks.startAsyncTask(function()
    dispatch(request)          -- now withWriteAccessDo is legal
  end)
end
```

`dispatch` runs in an independent task, so it can sleep, yield and take the
catalog write lock. Batch loops inside a single `withWriteAccessDo` are fine for
settings updates (`applyDevelopSettings` per photo in a loop is normal); the one
operation that wants one lock **per photo** is importing files.

## 3. pcall vs LrTasks.pcall

Plain `pcall` is a C function. If the protected function yields inside it, the
sandbox rejects the yield. Use `LrTasks.pcall` for anything that might sleep,
prompt, or take the write lock.

## 4. Checklist before blaming Lightroom

1. `luac -p` every `.lua` file with a **5.1** compiler. Lua 5.4+ rejects legal
   5.1 constructs (`attempt to assign to const variable`), and chasing that as a
   logic bug wastes hours. `lrc-kit preflight syntax` does this for you.
2. Is `LrForceInitPlugin` present **and** at least one menu item defined?
3. Did anything in the info-provider module body mutate state?
4. Is the write path inside `LrTasks.startAsyncTask`?
5. Did you use `LrTasks.pcall` rather than `pcall`?
6. After install: did you fully quit and reopen Lightroom, then press start once?
