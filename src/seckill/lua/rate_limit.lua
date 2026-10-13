-- One key per fixed window starting at the first accepted request.
if #KEYS ~= 1 or #ARGV ~= 2 then return 0 end
local limit, ttl = tonumber(ARGV[1]), tonumber(ARGV[2])
if not limit or not ttl or limit < 1 or ttl < 1 then return 0 end
local kind=redis.call('TYPE',KEYS[1]).ok
if kind ~= 'none' and kind ~= 'string' then return 0 end
local raw=redis.call('GET',KEYS[1]); local count=raw and tonumber(raw) or 0
if not count or count >= limit then return 0 end
if raw then redis.call('SET',KEYS[1],tostring(count+1),'KEEPTTL')
else redis.call('SET',KEYS[1],'1','PX',ARGV[2]) end
return 1
