-- The info provider is re-evaluated on every render of the Plug-in Manager
-- panel. Nothing in this module body may start, stop or reset the bridge -
-- doing so kills a live server just because the user opened the manager.
local LrView = import 'LrView'
local bind = LrView.bind

local function sectionsForTopOfDialog(f, propertyTable)
  return {
    {
      title = "Status",
      f:row {
        f:static_text {
          title = bind('statusText'),
        },
      },
      f:row {
        f:push_button {
          title = "Start / Show Status",
          action = function()
            local bridge = _G.ExampleBridge
            if bridge and not bridge.state.running then
              bridge.start()
            end
            propertyTable.statusText = bridge and bridge.state.running
              and ("Running: " .. tostring(bridge.state.dir))
              or "Not running"
          end,
        },
      },
    },
  }
end

return {
  sectionsForTopOfDialog = sectionsForTopOfDialog,
}
