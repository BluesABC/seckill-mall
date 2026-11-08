/**
 * 同源HTTP、会话及请求恢复工具。所有业务ID/分金额保留字符串，不自动重试变更请求。
 * 阅读导航：docs/CODE-READING.md；接口契约：docs/API.md。
 */
/**
 * 一行真实SKU；同款goodsId可对应多个独立尺码skuId，库存不能按款式合并。
 */
export interface Goods {
  goodsId: string;
  skuId: string;
  title: string;
  description: string;
  imageUrl: string;
  priceFen: string;
  unallocatedStock: string;
  sizeEu?:string;
  category?:string;
  colorway?:string;
}
export interface Activity {
  activityId: string;
  skuId: string;
  name: string;
  status: string;
  startsAtMs: string;
  endsAtMs: string;
  priceFen: string;
  availableStock: string;
  initialStock?:string;
  title: string;
  imageUrl: string;
}
export interface Session {
  token: string;
  userId: string;
  role: string;
  expiresAtMs: string;
}
/**
 * 异步查询模型：orderId为null仍可能已预留；requestState与orderState是两个不同状态机。
 */
export interface Order {
  title?: string;
  imageUrl?: string;
  sizeEu?: string;
  quantity?: string;
  orderId: string | null;
  requestId?: string;
  reservationId?: string;
  requestState?: string;
  orderState: string | null;
  amountFen: string | null;
  expiresAtMs?: string | null;
  skuId?: string;
  createdAtMs?: string;
  failureCode?: string | null;
}
/**
 * 本地请求恢复标识；submitted在发送buy之前写入，不代表后端已经受理成功。
 */
export interface Attempt {
  addressId?: string;
  userId: string;
  activityId: string;
  skuId: string;
  requestId: string;
  submitted: boolean;
}
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public retryable = false,
  ) {
    super(message);
  }
}
const sessionKey = "shijian.session";
/**
 * 只从本标签页sessionStorage读取会话；本地格式通过不等于服务端鉴权通过。
 */
export function readSession(): Session | null {
  try {
    const s = JSON.parse(sessionStorage.getItem(sessionKey) || "null");
    return s && typeof s.token === "string" && /^[0-9a-f]{64}$/.test(s.token)
      ? s
      : null;
  } catch {
    return null;
  }
}
export function saveSession(s: Session | null) {
  s
    ? sessionStorage.setItem(sessionKey, JSON.stringify(s))
    : sessionStorage.removeItem(sessionKey);
}
/**
 * 同源请求统一封装；传输错误标为NETWORK_UNKNOWN，不自动重发可能已生效的写请求。
 */
export async function api<T>(
  path: string,
  session: Session | null = null,
  body?: unknown,
  method?: string,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(session ? { Authorization: `Bearer ${session.token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(
      "NETWORK_UNKNOWN",
      "连接中断，请查询结果后再重试。",
      0,
      true,
    );
  }
  const data = await response
    .json()
    .catch(() => ({
      code: "INVALID_RESPONSE",
      message: "服务返回异常，请稍后重试。",
    }));
  if (!response.ok) {
    if (response.status === 401 && session) {
      saveSession(null);
      window.dispatchEvent(new Event("mall-session-expired"));
    }
    throw new ApiError(
      data.code || "UNKNOWN",
      data.message || "操作暂未完成",
      response.status,
      !!data.retryable,
    );
  }
  return data as T;
}
/**
 * 以BigInt格式化整数“分”，避免金额经浮点乘除丢失精度。
 */
export function money(fen: string | null | undefined) {
  try {
    const n = BigInt(fen || "0");
    return `${n / 100n}.${(n % 100n).toString().padStart(2, "0")}`;
  } catch {
    return "—";
  }
}
export function date(ms: string | null | undefined) {
  return ms
    ? new Date(Number(ms)).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
}
const messages: Record<string, string> = {
  ADDRESS_REQUIRED: '请先填写并选择完整收货信息，再提交抢购。',
  ADDRESS_NOT_FOUND: '收货地址不存在或不属于当前账号，请重新选择。',
  CHECKOUT_CONFLICT: '本次抢购已保存收货快照，请沿用原地址重试。',
  ORDER_DELETE_NOT_ALLOWED: '请先取消或退款；待发货、待收货订单不能直接删除。',
  WECHAT_NOT_CONFIGURED: '微信支付尚未配置，当前不能收款。',
  USE_WECHAT_PAYMENT: '请使用此订单的微信扫码支付入口。',
  WECHAT_PAYMENT_MANAGED: '这笔订单由微信处理，请在微信收银区查询或关闭。',
  USE_WECHAT_CLOSE: '请使用“关闭微信支付并取消订单”，等待微信确认。',
  WECHAT_RESULT_UNKNOWN: '微信响应尚未确认，请查询原订单，不要重复付款。',
  WECHAT_CLOSE_UNKNOWN: '微信关单结果尚未确认，订单暂未取消，请稍后查询。',
  WECHAT_REFUND_UNKNOWN: '退款结果尚未确认，请稍后查询原退款记录。',
  WECHAT_RECHECK_PENDING: '暂无法核实微信结果，记录已保留，请稍后重查。',
  WECHAT_PAYMENT_MISMATCH: '微信支付信息与订单不一致，请联系管理员核查。',
  PAYMENT_NOT_SETTLED: '支付或退款尚未确认，暂不能发货。',
  REFUND_NOT_ALLOWED: '当前订单暂不能直接退款，请核对支付和发货状态。',
  AMOUNT_OUT_OF_RANGE: '订单金额超出当前支付渠道支持范围。',

  SKU_IN_USE:'该 SKU 已参与活动，尺码与配色已锁定。请创建新的鞋款 SKU。',
  SKU_SIZE_EXISTS: '该鞋款已存在这个尺码。',
  UNAUTHORIZED: "请登录后继续。",
  FORBIDDEN: "当前账号没有此操作权限。",
  SOLD_OUT: "这件好物已售罄。",
  ALREADY_PURCHASED: "你已参与过本场活动，请查看订单。",
  NOT_STARTED: "活动还未开始。",
  ENDED: "活动已经结束。",
  INVALID_PROOF: "验证码或抢购凭证已失效，请重新验证。",
  ORDER_CLOSED: "订单已关闭，无法继续支付。",
  REQUEST_CONFLICT: "请求记录冲突，请查询已有订单。",
  ACCEPTANCE_UNKNOWN: "服务正在确认受理结果，请保留此请求并继续查询。",
};
export function message(e: unknown) {
  return e instanceof ApiError
    ? messages[e.code] || e.message
    : "操作未完成，请稍后重试。";
}
/**
 * 按userId隔离本浏览器抢购记录；本地记录不是服务端库存或订单事实。
 */
export function attempts(userId: string): Attempt[] {
  try {
    return JSON.parse(
      localStorage.getItem(`shijian.attempts.${userId}`) || "[]",
    );
  } catch {
    return [];
  }
}
/**
 * 同用户同活动SKU保存一笔请求身份，页面刷新/重新验证继续使用原requestId。
 */
export function remember(a: Attempt) {
  const list = attempts(a.userId).filter(
    (x) => x.activityId !== a.activityId || x.skuId !== a.skuId,
  );
  localStorage.setItem(
    `shijian.attempts.${a.userId}`,
    JSON.stringify([...list, a]),
  );
}
/**
 * 为同用户同订单持久保存支付幂等键，网络异常后继续使用，不重新生成。
 */
export function paymentKey(userId: string, orderId: string) {
  const key = `shijian.pay.${userId}.${orderId}`;
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID();
    localStorage.setItem(key, value);
  }
  return value;
}

/** 支付模式只在页面会话内缓存，配置失败不默认为微信可用；重新部署后刷新页面。 */
export interface PaymentConfig { provider: 'MOCK'|'WECHAT'; wechatConfigured:boolean; }
let paymentConfigPromise:Promise<PaymentConfig>|null=null;
export function paymentConfig():Promise<PaymentConfig>{
  if(!paymentConfigPromise)paymentConfigPromise=api<PaymentConfig>('/api/payments/config').catch(e=>{paymentConfigPromise=null;throw e;});
  return paymentConfigPromise;
}

/** Format the persisted payment deadline without changing order state on the client. */
export function paymentRemaining(deadline: string | null | undefined, now: number): string {
  const expires = Number(deadline);
  if (!Number.isFinite(expires) || expires <= 0) return '截止时间待确认';
  const seconds = Math.ceil((expires - now) / 1000);
  if (seconds <= 0) return '支付期限已到，等待系统确认订单状态';
  return '剩余 ' + Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
}
