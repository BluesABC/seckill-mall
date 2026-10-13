-- Trusted relay/consumer only; never called from a public endpoint.
-- ARGV: userId, requestId, reservationId, epoch, expectedState, nextState.
if #KEYS ~= 1 or #ARGV ~= 6 then return {'INVALID_ARGUMENT'} end
if redis.call('TYPE', KEYS[1]).ok ~= 'hash' then return {'NOT_READY'} end
if redis.call('HGET', KEYS[1], 'epoch') ~= ARGV[4] then return {'STALE_EPOCH'} end
local field = 'req:' .. ARGV[1] .. ':' .. ARGV[2]
local raw = redis.call('HGET', KEYS[1], field)
if not raw then return {'NOT_FOUND'} end
local req = cjson.decode(raw)
if req.reservationId ~= ARGV[3] then return {'RESERVATION_CONFLICT'} end
local function confirm_pending(value)
  local rawPending=redis.call('HGET',KEYS[1],'pending:'..ARGV[3])
  if not rawPending or rawPending=='' then return end
  local count=tonumber(redis.call('HGET',KEYS[1],'pendingCount') or '0')
  if not count or count<1 then return end
  redis.call('HSET',KEYS[1],field,value,'pending:'..ARGV[3],'','pendingCount',tostring(count-1))
end
if req.state == ARGV[6] then
  if (ARGV[6]=='QUEUED' and ARGV[5]=='RESERVED') or
     (ARGV[6]=='ORDER_CREATED' and ARGV[5]=='QUEUED') then
    confirm_pending(raw)
    return {'REPLAY',raw}
  end
  return {'STATE_CONFLICT'}
end
if req.state=='ORDER_CREATED' and ARGV[5]=='RESERVED' and ARGV[6]=='QUEUED' then
  confirm_pending(raw)
  return {'ALREADY_ADVANCED',raw}
end
if req.state ~= ARGV[5] then return {'STATE_CONFLICT'} end
local allowed = (ARGV[5] == 'RESERVED' and (ARGV[6] == 'QUEUED' or ARGV[6] == 'COMPENSATING')) or
  (ARGV[5] == 'QUEUED' and (ARGV[6] == 'ORDER_CREATED' or ARGV[6] == 'COMPENSATING'))
if not allowed then return {'STATE_CONFLICT'} end
req.state = ARGV[6]
if req.state == 'ORDER_CREATED' then req.orderState = 'PENDING_PAYMENT' end
local value = cjson.encode(req)
-- Tombstone the pending field only after confirmed delivery/creation.
if req.state == 'QUEUED' or req.state == 'ORDER_CREATED' then
  local rawPending=redis.call('HGET',KEYS[1],'pending:'..ARGV[3])
  local count=tonumber(redis.call('HGET',KEYS[1],'pendingCount') or '0')
  if rawPending and rawPending~='' and count>0 then count=count-1 end
  redis.call('HSET', KEYS[1], field, value, 'pending:' .. ARGV[3], '', 'pendingCount',tostring(count))
else redis.call('HSET', KEYS[1], field, value) end
return {'UPDATED', value}
