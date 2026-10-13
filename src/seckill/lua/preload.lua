-- Admin-only, first initialization. Never overwrite a live ledger.
-- ARGV: stock, startsAtMs, endsAtMs, status, epoch, priceFen, activityId, skuId.
if #KEYS ~= 1 or #ARGV ~= 8 then return {'INVALID_ARGUMENT'} end
if redis.call('EXISTS', KEYS[1]) == 1 then return {'ALREADY_INITIALIZED'} end
local stock, starts, ends = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
if not stock or stock < 0 or stock > 4294967295 or stock % 1 ~= 0 or
   not starts or not ends or ends <= starts or starts < 0 then return {'INVALID_ARGUMENT'} end
for _, i in ipairs({5, 6, 7, 8}) do
  if not string.match(ARGV[i], '^[1-9]%d*$') or #ARGV[i] > 19 then return {'INVALID_ARGUMENT'} end
end
if ARGV[4] ~= 'ACTIVE' and ARGV[4] ~= 'READY' then return {'INVALID_ARGUMENT'} end
redis.call('HSET', KEYS[1], 'stock', ARGV[1], 'initialStock', ARGV[1],
  'startsAtMs', ARGV[2], 'endsAtMs', ARGV[3], 'status', ARGV[4], 'epoch', ARGV[5],
  'priceFen', ARGV[6], 'activityId', ARGV[7], 'skuId', ARGV[8], 'pendingCount','0')
return {'INITIALIZED'}
