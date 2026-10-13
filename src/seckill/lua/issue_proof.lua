-- Single atomic update of the existing challenge JSON, preserving its TTL.
-- ARGV userId, requestId, answerDigest, captchaDigest, activityDigest, epoch.
if #KEYS ~= 1 or #ARGV ~= 6 then return {'INVALID_ARGUMENT'} end
local raw=redis.call('GET',KEYS[1]); if not raw then return {'INVALID_PROOF'} end
local proof=cjson.decode(raw)
local now=redis.call('TIME'); local nowMs=tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000)
if proof.userId~=ARGV[1] or proof.epoch~=ARGV[6] or proof.used or proof.expiresAtMs<=nowMs or proof.attempts>=5 then return {'INVALID_PROOF'} end
if proof.answerDigest~=ARGV[3] then
  proof.attempts=proof.attempts+1
  redis.call('SET',KEYS[1],cjson.encode(proof),'KEEPTTL')
  return {'INVALID_PROOF'}
end
proof.used=true; proof.requestId=ARGV[2];proof.captchaDigest=ARGV[4];proof.activityDigest=ARGV[5]
proof.answerDigest=nil
redis.call('SET',KEYS[1],cjson.encode(proof),'KEEPTTL')
return {'ISSUED',string.format('%.0f',proof.expiresAtMs)}
