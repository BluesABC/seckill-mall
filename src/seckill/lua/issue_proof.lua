-- 职责：原子验证答案并将挑战兑换成绑定用户/请求/epoch的证明；失败累计至最多5次。
-- KEYS：[1]挑战JSON；ARGV依次为userId、requestId、答案摘要、captchaToken摘要、activityToken摘要、epoch。
-- 校验使用Redis TIME；KEEPTTL保留最初60秒期限，不能在兑换时续期。
-- 返回：ISSUED及到期毫秒，或INVALID_PROOF/INVALID_ARGUMENT；成功后删除答案摘要。

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
