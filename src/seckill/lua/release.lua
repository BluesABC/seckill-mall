-- Execute only after durable DB termination/closed outbox evidence.
-- KEYS[1] ledger, KEYS[2] active relay-ledger registry,
-- KEYS[3] per-ledger pending reservation set.
-- ARGV userId, requestId, reservationId, epoch, eventId, reason (FAILED/CLOSED).
if (#KEYS ~= 1 and #KEYS ~= 3) or #ARGV ~= 6 then return {'INVALID_ARGUMENT'} end
if ARGV[6] ~= 'FAILED' and ARGV[6] ~= 'CLOSED' then return {'INVALID_ARGUMENT'} end
if not string.match(ARGV[5], '^[%w%-]+$') or #ARGV[5] > 64 then return {'INVALID_ARGUMENT'} end
if redis.call('TYPE', KEYS[1]).ok ~= 'hash' then return {'NOT_READY'} end
if redis.call('HGET', KEYS[1], 'epoch') ~= ARGV[4] then return {'STALE_EPOCH'} end
local marker = ARGV[3] .. ':' .. ARGV[6]
local prior = redis.call('HGET', KEYS[1], 'release:' .. ARGV[5])
if prior then
  if prior == marker then return {'REPLAY'} end
  return {'RELEASE_CONFLICT'}
end
local field = 'req:' .. ARGV[1] .. ':' .. ARGV[2]
local raw = redis.call('HGET', KEYS[1], field)
if not raw then return {'NOT_FOUND'} end
local req = cjson.decode(raw)
if req.reservationId ~= ARGV[3] or redis.call('HGET', KEYS[1], 'user:' .. ARGV[1]) ~= ARGV[3] then
  return {'RESERVATION_CONFLICT'}
end
-- Reservation-level marker also prevents two different events releasing the same stock.
if req.released == true then return {'ALREADY_RELEASED'} end
if ARGV[6] == 'FAILED' then
  if req.state ~= 'COMPENSATING' then return {'STATE_CONFLICT'} end
  req.state = 'FAILED'
else
  if req.state ~= 'ORDER_CREATED' or req.orderState ~= 'CLOSED' then return {'STATE_CONFLICT'} end
end
local stock = tonumber(redis.call('HGET', KEYS[1], 'stock'))
local initial = tonumber(redis.call('HGET', KEYS[1], 'initialStock'))
if not stock or not initial or stock < 0 or stock % 1 ~= 0 or stock >= initial then
  return {'STOCK_CONFLICT'}
end
req.released = true
local value = cjson.encode(req)
local rawPending=redis.call('HGET',KEYS[1],'pending:'..ARGV[3])
local pending=tonumber(redis.call('HGET',KEYS[1],'pendingCount') or '0')
if rawPending and rawPending~='' then pending=math.max(0,pending-1) end
-- Preserve user qualification; tombstone pending so relay does not send failed requests.
redis.call('HSET', KEYS[1], 'stock', tostring(stock + 1), field, value,
  'release:' .. ARGV[5], marker, 'pending:' .. ARGV[3], '', 'pendingCount',tostring(pending))
if rawPending and rawPending~='' and KEYS[3] then redis.call('SREM',KEYS[3],ARGV[3]) end
if pending==0 and KEYS[2] then redis.call('SREM',KEYS[2],KEYS[1]) end
return {'RELEASED'}
