-- Minimal skeleton: the three Info.lua fields that decide whether your plugin
-- loads eagerly and whether it can be started without hunting through menus.
return {
  LrSdkVersion = 8.0,
  LrSdkMinimumVersion = 8.0,
  LrToolkitIdentifier = 'com.example.lrcbridge',
  LrPluginName = "Example Bridge",

  VERSION = { major = 0, minor = 1, revision = 0 },

  LrPluginInfoProvider = 'PluginInfoProvider.lua',
  LrInitPlugin = 'Bridge.lua',

  -- Eager load at startup. Only honoured because a menu item is exposed below;
  -- without LrLibraryMenuItems this flag does nothing.
  LrForceInitPlugin = true,
  LrLibraryMenuItems = {
    { title = "Example Bridge - Show Status", file = "MenuShowStatus.lua" },
  },
}
