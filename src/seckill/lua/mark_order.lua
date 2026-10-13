-- Mirror committed MySQL state only. ARGV userId, requestId, reservationId, epoch, nextState.
if #KEYS ~= 1 or #ARGV ~= 5 then return {'INVALID_ARGUMENT'} end
if redis.call('TYPE', KEYS[1]).ok ~= 'hash' then return {'NOT_READY'} end
if redis.call('HGET', KEYS[1], 'epoch') ~= ARGV[4] then return {'STALE_EPOCH'} end
local field = 'req:' .. ARGV[1] .. ':' .. ARGV[2]
local raw = redis.call('HGET', KEYS[1], field)
if not raw then return {'NOT_FOUND'} end
local req = cjson.decode(raw)
if req.reservationId ~= ARGV[3] then return {'RESERVATION_CONFLICT'} end
if req.state ~= 'ORDER_CREATED' then return {'STATE_CONFLICT'} end
if req.orderState == ARGV[5] then return {'REPLAY', raw} end
if req.orderState ~= 'PENDING_PAYMENT' or (ARGV[5] ~= 'PAID' and ARGV[5] ~= 'CLOSED') then
  return {'STATE_CONFLICT'}
end
req.orderState = ARGV[5]
local value = cjson.encode(req)
redis.call('HSET', KEYS[1], field, value)
return {'UPDATED', value}
