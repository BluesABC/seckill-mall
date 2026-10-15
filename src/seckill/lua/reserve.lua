-- One hash per activity/SKU: all checks precede ONE mutating HSET.
-- KEYS[1] = seckill:{activityId:skuId}:ledger
-- KEYS[3] (secured calls) = active relay-ledger registry
-- KEYS[4] (secured calls) = per-ledger pending reservation set
-- ARGV: userId, requestId, reservationId, epoch, traceId
-- Values come from the authenticated service, never raw client identity/price.
local secured = #KEYS == 4 and #ARGV == 8
if not secured and (#KEYS ~= 1 or #ARGV ~= 5) then return {'INVALID_ARGUMENT'} end
local function id(s) return #s > 0 and #s <= 64 and string.match(s, '^[%w%-]+$') end
local function uuid(s)
  if #s ~= 36 then return false end
  local expected, count = {8, 4, 4, 4, 12}, 0
  for part in string.gmatch(s, '[^%-]+') do
    count = count + 1
    if count > 5 or #part ~= expected[count] or not string.match(part, '^[0-9a-f]+$') then return false end
  end
  return count == 5
end
local function user(s)
  return string.match(s, '^[1-9]%d*$') and (#s < 19 or (#s == 19 and s <= '9223372036854775807'))
end
if not user(ARGV[1]) or not uuid(ARGV[2]) or not uuid(ARGV[3]) or not id(ARGV[5]) then
  return {'INVALID_ARGUMENT'}
end
local kind = redis.call('TYPE', KEYS[1]).ok
if kind ~= 'hash' then return {'NOT_READY'} end
local requestField = 'req:' .. ARGV[1] .. ':' .. ARGV[2]
local prior = redis.call('HGET', KEYS[1], requestField)
if prior then return {'REPLAY', prior} end
local fields = redis.call('HMGET', KEYS[1], 'stock', 'startsAtMs', 'endsAtMs',
  'status', 'epoch', 'priceFen', 'activityId', 'skuId')
local stock, starts, ends, price = tonumber(fields[1]), tonumber(fields[2]),
  tonumber(fields[3]), tonumber(fields[6])
if not stock or stock < 0 or stock > 4294967295 or stock % 1 ~= 0 or
   not starts or starts < 0 or not ends or ends <= starts or
   not price or price <= 0 or not fields[7] or not fields[8] then return {'NOT_READY'} end
if fields[5] ~= ARGV[4] then return {'STALE_EPOCH'} end
local now = redis.call('TIME')
local nowMs = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
if secured then
  local raw=redis.call('GET',KEYS[2])
  if not raw then return {'INVALID_PROOF'} end
  local proof=cjson.decode(raw)
  if proof.used~=true or proof.userId~=ARGV[1] or proof.requestId~=ARGV[2] or
     proof.epoch~=ARGV[4] or proof.activityId~=fields[7] or proof.skuId~=fields[8] or
     proof.captchaDigest~=ARGV[6] or proof.activityDigest~=ARGV[7] or proof.expiresAtMs<=nowMs then
    return {'INVALID_PROOF'}
  end
end
if nowMs < starts then return {'NOT_STARTED'} end
if nowMs >= ends then return {'ENDED'} end
if fields[4] ~= 'ACTIVE' then return {'NOT_READY'} end
if redis.call('HEXISTS', KEYS[1], 'user:' .. ARGV[1]) == 1 then return {'ALREADY_PURCHASED'} end
if stock == 0 then return {'SOLD_OUT'} end
local pending=tonumber(redis.call('HGET',KEYS[1],'pendingCount') or '0')
if not pending or pending<0 then return {'NOT_READY'} end
if secured and pending>=tonumber(ARGV[8]) then return {'BACKPRESSURE'} end
-- Serialize BEFORE mutation; all numeric IDs and money are decimal strings.
local event = cjson.encode({schemaVersion=1, eventId=ARGV[3], eventType='SECKILL_RESERVED',
  reservationId=ARGV[3], requestId=ARGV[2], userId=ARGV[1], activityId=fields[7],
  skuId=fields[8], epoch=fields[5], quantity=1, priceFen=fields[6],
  createdAtMs=string.format('%.0f', nowMs), traceId=ARGV[5]})
local request = cjson.encode({reservationId=ARGV[3], requestId=ARGV[2],
  state='RESERVED', createdAtMs=string.format('%.0f', nowMs)})
redis.call('HSET', KEYS[1], 'stock', tostring(stock - 1),
  'user:' .. ARGV[1], ARGV[3], requestField, request, 'pending:' .. ARGV[3], event,
  'pendingCount',tostring(pending+1))
if secured then
  redis.call('SADD', KEYS[3], KEYS[1])
  redis.call('SADD', KEYS[4], ARGV[3])
end
return {'RESERVED', request}
