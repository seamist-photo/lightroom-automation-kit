-- A menu item is not optional decoration: LrForceInitPlugin is ignored unless
-- at least one menu item exists, and this is also the manual fallback when
-- lazy loading wins despite it.
local LrDialogs = import 'LrDialogs'

local function run()
  local bridge = _G.ExampleBridge
  if not bridge then
    LrDialogs.message("Example Bridge", "Bridge module has not loaded yet.", "info")
    return
  end
  local state = bridge.state
  if not state.running then
    local ok, info = bridge.start()
    LrDialogs.message("Example Bridge", "Started. Watching: " .. tostring(info), "info")
    return
  end
  LrDialogs.message(
    "Example Bridge",
    string.format("Running.\nDirectory: %s\nHandled: %d", tostring(state.dir), state.handled or 0),
    "info"
  )
end

run()
