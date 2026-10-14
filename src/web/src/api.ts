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
export interface Order {
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
export interface Attempt {
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
export function attempts(userId: string): Attempt[] {
  try {
    return JSON.parse(
      localStorage.getItem(`shijian.attempts.${userId}`) || "[]",
    );
  } catch {
    return [];
  }
}
export function remember(a: Attempt) {
  const list = attempts(a.userId).filter(
    (x) => x.activityId !== a.activityId || x.skuId !== a.skuId,
  );
  localStorage.setItem(
    `shijian.attempts.${a.userId}`,
    JSON.stringify([...list, a]),
  );
}
export function paymentKey(userId: string, orderId: string) {
  const key = `shijian.pay.${userId}.${orderId}`;
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID();
    localStorage.setItem(key, value);
  }
  return value;
}
