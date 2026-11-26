-- Per-frame telemetry for the General bot (Ikemen GO 1.0.x).
-- Unlike shared_telemetry.lua (every 3 frames, raw posX in each character's own
-- localcoord), this writes EVERY frame and includes engine-computed distances from
-- each player's point of view, so characters with different localcoords
-- (320p vs 720p) are measured correctly.
local OUTPUT = 'general_bot_telemetry.json'
local tick = 0
local KEYS = {
  'state_no', 'time', 'anim_time', 'ctrl', 'state_type', 'move_type', 'hp', 'power',
  'y', 'vx', 'vy', 'facing', 'body_dist_x', 'body_dist_y', 'in_guard_dist',
  'front_edge', 'back_edge', 'move_hit', 'move_contact', 'move_guarded', 'hit_pause', 'num_proj', 'name',
  'win', 'lose', 'ai_level'
}
local function get(fn)
  if type(fn) ~= 'function' then return nil end
  local ok, v = pcall(fn)
  if ok then return v end
  return nil
end
local function enc(v)
  local t = type(v)
  if v == nil then return 'null' end
  if t == 'boolean' then return tostring(v) end
  if t == 'number' then
    if v ~= v or v == math.huge or v == -math.huge then return 'null' end
    return string.format('%.6g', v)
  end
  return '"' .. tostring(v):gsub('[%c"\\]', '') .. '"'
end
local function snap(slot)
  local ok, sel = pcall(player, slot)
  if not ok or sel ~= true then return nil end
  local ctrlv = get(ctrl)
  if type(ctrlv) == 'number' then ctrlv = ctrlv ~= 0 end
  return {
    state_no = get(stateNo), time = get(time), anim_time = get(animTime), ctrl = ctrlv,
    state_type = get(stateType), move_type = get(moveType), hp = get(life), power = get(power),
    y = get(posY), vx = get(velX), vy = get(velY), facing = get(facing),
    body_dist_x = get(p2BodyDistX), body_dist_y = get(p2BodyDistY), in_guard_dist = get(inGuardDist),
    front_edge = get(frontEdgeBodyDist), back_edge = get(backEdgeBodyDist),
    move_hit = get(moveHit), move_contact = get(moveContact), move_guarded = get(moveGuarded),
    hit_pause = get(hitPauseTime), num_proj = get(numProj), name = get(name),
    win = get(win), lose = get(lose), ai_level = get(aiLevel),
  }
end
local function obj(p)
  local parts = {}
  for _, k in ipairs(KEYS) do parts[#parts + 1] = '"' .. k .. '":' .. enc(p[k]) end
  return '{' .. table.concat(parts, ',') .. '}'
end
local function update()
  tick = tick + 1
  local p1, p2 = snap(1), snap(2)
  if not p1 or not p2 then return end
  local rn, rs = get(roundNo), get(roundState)
  local s = '{"tick":' .. tick .. ',"round_no":' .. enc(rn) .. ',"round_state":' .. enc(rs) .. ',"p1":' .. obj(p1) .. ',"p2":' .. obj(p2) .. '}\n'
  local tmp = OUTPUT .. '.tmp'
  local f = io.open(tmp, 'wb')
  if not f then return end
  f:write(s)
  f:close()
  if not os.rename(tmp, OUTPUT) then
    local g = io.open(OUTPUT, 'wb')
    if g then g:write(s); g:close() end
    os.remove(tmp)
  end
end
if type(hook) == 'table' and type(hook.add) == 'function' then
  hook.add('loop', 'general_bot_telemetry', function() pcall(update) end)
end
