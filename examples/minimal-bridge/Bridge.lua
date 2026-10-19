-- Minimal file-protocol bridge: watch an inbox directory, execute one command
-- per file, write the reply to outbox.
--
-- Deliberately simple, and it demonstrates the two context rules that matter:
--   1. the polling loop must be started with postAsyncTaskWithContext, because
--      this script is an init script and its context dies on return;
--   2. the command execution happens inside a task, so it may yield and may
--      take the catalog write lock.
local LrTasks = import 'LrTasks'
local LrFunctionContext = import 'LrFunctionContext'
local LrPathUtils = import 'LrPathUtils'
local LrFileUtils = import 'LrFileUtils'
local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'

local STATE = { running = false, dir = nil, handled = 0 }

local function log(msg)
  -- Replace with LrLogger or a file sink in a real plugin.
  if LrDialogs and LrDialogs.message then
    -- no-op by default: keep the skeleton quiet while polling
  end
end

local function join(dir, name)
  return LrPathUtils.child(dir, name)
end

local function readFile(path)
  local fh = io.open(path, 'r')
  if not fh then return nil end
  local body = fh:read('*a')
  fh:close()
  return body
end

local function writeFile(path, body)
  local fh = io.open(path, 'w')
  if not fh then return false end
  fh:write(body)
  fh:close()
  return true
end

-- A tiny command table. Each handler receives the raw text and returns a table.
local COMMANDS = {}

COMMANDS.ping = function()
  return { ok = true, pong = os.time() }
end

COMMANDS.count = function()
  local catalog = LrApplication.activeCatalog()
  local n = 0
  catalog:withReadAccessDo(function()
    n = #catalog:getAllPhotos()
  end)
  return { ok = true, images = n }
end

-- Writing requires the catalog write lock. Note the entire batch runs inside a
-- single withWriteAccessDo: that is correct for settings updates. File imports
-- are the exception - use one lock per photo there.
COMMANDS.rate = function(payload)
  local photoId = tonumber(payload.photo_id)
  local stars = tonumber(payload.rating) or 0
  if not photoId then return { ok = false, error = 'photo_id required' } end

  local catalog = LrApplication.activeCatalog()
  local applied = false
  catalog:withWriteAccessDo("Example Bridge: set rating", function()
    for _, photo in ipairs(catalog:getAllPhotos()) do
      if photo.localIdentifier == tostring(photoId) then
        photo:setRawRating(stars)
        applied = true
        break
      end
    end
  end)
  return { ok = applied, rating = stars }
end

-- Crude JSON writer: the skeleton has no dependency, and the replies are flat.
local function encode(tbl)
  local parts = {}
  for k, v in pairs(tbl) do
    local val
    if type(v) == 'string' then
      val = '"' .. v:gsub('"', '\\"') .. '"'
    elseif type(v) == 'number' or type(v) == 'boolean' then
      val = tostring(v)
    else
      val = 'null'
    end
    parts[#parts + 1] = '"' .. k .. '":' .. val
  end
  table.sort(parts)
  return '{' .. table.concat(parts, ',') .. '}'
end

local function handleOneFile(path)
  local body = readFile(path) or ''
  local cmd, rest = body:match('^%s*([%w_]+)%s*(.*)$')
  local reply
  if cmd and COMMANDS[cmd] then
    -- LrTasks.pcall, not pcall: the handler yields inside the write lock.
    local ok, result = LrTasks.pcall(COMMANDS[cmd], rest)
    if ok then
      reply = result
    else
      reply = { ok = false, error = tostring(result) }
    end
  else
    reply = { ok = false, error = 'unknown command: ' .. tostring(cmd) }
  end
  local out = join(STATE.dir, 'outbox') .. '/' .. LrPathUtils.leafName(path)
  LrFileUtils.createAllDirectories(join(STATE.dir, 'outbox'))
  writeFile(out, encode(reply))
  LrFileUtils.delete(path)      -- delete AFTER the reply is written
  STATE.handled = STATE.handled + 1
end

local function pollLoop()
  LrTasks.startAsyncTask(function()
    while STATE.running do
      local entries = LrFileUtils.directoryEntries(join(STATE.dir, 'inbox'))
      for _, path in ipairs(entries or {}) do
        if LrPathUtils.extension(path) == 'txt' then
          local ok, err = LrTasks.pcall(handleOneFile, path)
          if not ok then log('handler failed: ' .. tostring(err)) end
        end
      end
      LrTasks.sleep(1)
    end
  end)
end

local function start(dir)
  if STATE.running then return true, 'already running' end
  STATE.dir = dir or LrPathUtils.child(LrPathUtils.getStandardFilePath('temp'), 'lrc-bridge')
  LrFileUtils.createAllDirectories(join(STATE.dir, 'inbox'))
  LrFileUtils.createAllDirectories(join(STATE.dir, 'outbox'))
  STATE.running = true
  pollLoop()
  return true, STATE.dir
end

local function stop()
  STATE.running = false
  return true
end

-- Exposed so the info panel / menu can call them.
_G.ExampleBridge = { start = start, stop = stop, state = STATE }

-- Auto-start. postAsyncTaskWithContext, because this is an init script: a bare
-- startAsyncTask here would be cancelled the moment the script returns.
LrFunctionContext.postAsyncTaskWithContext("ExampleBridgeAutoStart", function()
  LrTasks.sleep(0.5)
  local ok, err = LrTasks.pcall(start)
  if not ok then log('auto-start failed: ' .. tostring(err)) end
end)
