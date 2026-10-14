<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import {
  api,
  ApiError,
  attempts,
  remember,
  paymentKey,
  readSession,
  saveSession,
  money,
  date,
  message,
  type Goods,
  type Activity,
  type Session,
  type Order,
  type Attempt,
} from "./api";
import Admin from "./Admin.vue";
import ShopFront from "./ShopFront.vue";
import ShoeDetail from "./ShoeDetail.vue";
import ShoppingBag from "./ShoppingBag.vue";
import "./style.css";
import "./sports.css";
const session = ref<Session | null>(readSession()),
  route = ref(decodeRoute()),
  goods = ref<Goods[]>([]),
  catalogItems = ref<Goods[]>([]),
  catalogTotal = ref(0),
  catalogPage = ref(-1),
  catalogHasMore = ref(false),
  catalogLoading = ref(false),
  catalogError = ref(""),
  activities = ref<Activity[]>([]),
  loading = ref(true),
  error = ref(""),
  notice = ref(""),
  search = ref(""),
  sort = ref("featured"),
  order = ref<Order | null>(null),
  orders = ref<Order[]>([]),
  busy = ref(false),
  clock = ref(Date.now()),
  offset = ref(0),
  pollNote = ref(""),
  refreshing = ref(false);
type CatalogQuery = { q: string; category: string; maxPriceFen: string; sort: string };
const catalogQuery = ref<CatalogQuery>({ q: "", category: "", maxPriceFen: "", sort: "featured" });
let catalogRequest = 0;
const authOpen = ref(false),
  register = ref(false),
  username = ref(""),
  password = ref(""),
  authError = ref(""),
  authBusy = ref(false),
  returnTo = ref<string | null>(null),
  dialog = ref<HTMLDialogElement | null>(null),
  captchaOpen = ref(false),
  captcha = ref<{
    captchaId: string;
    mode: "image" | "accessible";
    imageDataUrl?: string;
    challengeText?: string;
    expiresAtMs: string;
  } | null>(null),
  captchaMode = ref<"image" | "accessible">("image"),
  answer = ref(""),
  captchaError = ref(""),
  attempt = ref<Attempt | null>(null),
  info = ref<{
    state: string;
    stockAvailable: boolean;
    startsAtMs: string;
    endsAtMs: string;
    serverTimeMs: string;
  } | null>(null),
  infoError = ref("");
let timer: ReturnType<typeof setTimeout> | undefined,
  ticker: ReturnType<typeof setInterval> | undefined,
  controller: AbortController | undefined,
  generation = 0,
  opener: HTMLElement | null = null;
const page = computed(() => route.value.split("/")[1] || "home"),
  id = computed(() => route.value.split("/")[2] || ""),
  product = computed(() =>
    goods.value.find(
      (g) =>
        g.goodsId === id.value &&
        (!route.value.split("/")[3] || g.skuId === route.value.split("/")[3]),
    ),
  ),
  productActivity = computed(
    () =>
      activities.value.find(
        (a) => a.skuId === product.value?.skuId && a.status !== "ENDED",
      ) || activities.value.find((a) => a.skuId === product.value?.skuId),
  ),
  featured = computed(() => {
    let list = [...new Map(goods.value.map((g) => [g.goodsId, g])).values()].filter(
      (g) =>
        g.title.includes(search.value) || g.description.includes(search.value),
    );
    if (sort.value !== "featured")
      list = [...list].sort((a, b) =>
        BigInt(a.priceFen) === BigInt(b.priceFen)
          ? 0
          : (BigInt(a.priceFen) < BigInt(b.priceFen) ? -1 : 1) *
            (sort.value === "low" ? 1 : -1),
      );
    return list;
  }),
  currentAttempt = computed(() =>
    session.value
      ? attempts(session.value.userId).find((a) => a.requestId === id.value)
      : undefined,
  );
const stateLabel = (state: string | null | undefined) =>
  ({
    PENDING_PAYMENT: "待支付",
    PAID: "已支付",
    CLOSED: "已关闭",
    RESERVED: "已受理，正在确认订单",
    QUEUED: "已受理，正在确认订单",
    ORDER_CREATED: "订单已生成",
    COMPENSATING: "正在恢复处理",
    FAILED: "抢购未成功",
  })[state || ""] || "正在查询";
const countdown = computed(() => {
  const a = info.value;
  if (!a) return "";
  const now = clock.value + offset.value;
  const end = Number(now < Number(a.startsAtMs) ? a.startsAtMs : a.endsAtMs);
  const s = Math.max(0, Math.floor((end - now) / 1000));
  return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60]
    .map((n) => n.toString().padStart(2, "0"))
    .join(" : ");
});
const canBuy = computed(
  () =>
    info.value?.state === "ACTIVE" &&
    info.value.stockAvailable &&
    clock.value + offset.value >= Number(info.value.startsAtMs) &&
    clock.value + offset.value < Number(info.value.endsAtMs),
);
const buyLabel = computed(() => {
  if (!productActivity.value) return "暂无开放的限时活动";
  if (!info.value) return infoError.value ? "活动暂不可用" : "正在确认活动";
  if (
    info.value.state === "ENDED" ||
    clock.value + offset.value >= Number(info.value.endsAtMs)
  )
    return "本场活动已结束";
  if (
    clock.value + offset.value < Number(info.value.startsAtMs) ||
    info.value.state === "READY"
  )
    return "等待活动开始";
  if (!info.value.stockAvailable) return "本场已售罄";
  return "立即抢购";
});
const bagOpen = ref(false),
  bagIds = ref<string[]>([]);
function bagKey() {
  return "snkr.bag." + (session.value?.userId || "guest");
}
function readBag() {
  try {
    const value = JSON.parse(localStorage.getItem(bagKey()) || "[]");
    bagIds.value = Array.isArray(value)
      ? value.filter((x) => typeof x === "string" && /^[0-9]+$/.test(x))
      : [];
  } catch {
    bagIds.value = [];
  }
}
function storeBag() {
  localStorage.setItem(bagKey(), JSON.stringify(bagIds.value));
}
const bagItems = computed(() =>
  bagIds.value
    .map((sku) => goods.value.find((g) => g.skuId === sku))
    .filter((g): g is Goods => !!g),
);
function bagPrice(g: Goods) {
  return (
    activities.value.find((a) => a.skuId === g.skuId && a.status === "ACTIVE")
      ?.priceFen || g.priceFen
  );
}
const bagTotal = computed(() =>
  bagItems.value.reduce((sum, g) => sum + BigInt(bagPrice(g)), 0n).toString(),
);
function addBag() {
  if (product.value) {
    if (!bagIds.value.includes(product.value.skuId)) {
      bagIds.value.push(product.value.skuId);
      storeBag();
    }
    bagOpen.value = true;
  }
}
function removeBag(sku: string) {
  bagIds.value = bagIds.value.filter((s) => s !== sku);
  storeBag();
}
watch(session, () => {
  bagOpen.value = false;
  readBag();
});
onMounted(readBag);
function go(path: string) {
  location.hash = path;
}
function hash() {
  route.value = decodeRoute();
}
function decodeRoute(){try{return decodeURI(location.hash.slice(1)||'/')}catch{return '/not-found'}}
async function loadCatalog() {
  loading.value = true;
  error.value = "";
  const query: CatalogQuery = {
    q: search.value.trim(),
    category: page.value === "catalog" ? id.value : "",
    maxPriceFen: "",
    sort: "featured",
  };
  try {
    const [g, a] = await Promise.all([
      api<{ items: Goods[] }>("/api/goods"),
      api<{ items: Activity[] }>("/api/activities"),
    ]);
    goods.value = g.items;
    activities.value = a.items;
    await fetchCatalog(query);
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}
async function fetchCatalog(query: CatalogQuery, append = false) {
  if (append && catalogLoading.value) return;
  const request = ++catalogRequest;
  const pageNumber = append ? catalogPage.value + 1 : 0;
  catalogQuery.value = query;
  if (!append) {
    catalogItems.value = [];
    catalogTotal.value = 0;
    catalogHasMore.value = false;
    catalogPage.value = -1;
  }
  catalogLoading.value = true;
  catalogError.value = "";
  const params = new URLSearchParams({
    q: query.q,
    category: query.category,
    maxPriceFen: query.maxPriceFen,
    sort: query.sort,
    page: String(pageNumber),
    size: "12",
  });
  try {
    const result = await api<{
      items: Goods[]; page: number; size: number; total: number; hasMore: boolean;
    }>(`/api/goods/catalog?${params}`);
    if (request !== catalogRequest) return;
    catalogItems.value = append ? [...catalogItems.value, ...result.items] : result.items;
    const known = new Set(goods.value.map((g) => g.skuId));
    goods.value = [...goods.value, ...result.items.filter((g) => !known.has(g.skuId))];
    catalogPage.value = result.page;
    catalogTotal.value = result.total;
    catalogHasMore.value = result.hasMore;
  } catch (e) {
    if (request === catalogRequest) catalogError.value = message(e);
  } finally {
    if (request === catalogRequest) catalogLoading.value = false;
  }
}
function changeCatalog(query: CatalogQuery) {
  search.value = query.q;
  void fetchCatalog(query);
}
function loadMoreCatalog() {
  void fetchCatalog(catalogQuery.value, true);
}
async function loadInfo() {
  info.value = null;
  infoError.value = "";
  const a = productActivity.value;
  if (!a) return;
  const version = generation;
  try {
    const result = await api<{
      state: string;
      stockAvailable: boolean;
      startsAtMs: string;
      endsAtMs: string;
      serverTimeMs: string;
    }>(`/api/seckill/info?activityId=${a.activityId}&skuId=${a.skuId}`);
    if (version === generation) {
      info.value = result;
      offset.value = Number(result.serverTimeMs) - Date.now();
    }
  } catch (e) {
    if (version === generation) infoError.value = message(e);
  }
}
function openAuth(to?: string) {
  returnTo.value = to || null;
  register.value = false;
  authError.value = "";
  password.value = "";
  authOpen.value = true;
}
async function login() {
  authBusy.value = true;
  authError.value = "";
  try {
    if (register.value)
      await api("/api/auth/register", null, {
        username: username.value,
        password: password.value,
      });
    const s = await api<Session>("/api/auth/login", null, {
      username: username.value,
      password: password.value,
    });
    session.value = s;
    saveSession(s);
    password.value = "";
    authOpen.value = false;
    notice.value = register.value
      ? "账号已创建，欢迎来到 SNKR//DROP。"
      : "登录成功。";
    if (returnTo.value && returnTo.value !== route.value) go(returnTo.value);
    else await loadPage();
  } catch (e) {
    authError.value = message(e);
  } finally {
    authBusy.value = false;
  }
}
async function logout() {
  busy.value = true;
  try {
    await api("/api/auth/logout", session.value, undefined, "POST");
    saveSession(null);
    session.value = null;
    order.value = null;
    orders.value = [];
    go("/");
    notice.value = "已安全退出。";
  } catch (e) {
    notice.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function requireSession() {
  if (!session.value) {
    openAuth(route.value);
    return false;
  }
  return true;
}
async function startPurchase() {
  if (!(await requireSession())) return;
  const a = productActivity.value;
  if (!a || !session.value || !canBuy.value || busy.value) return;
  const previous = attempts(session.value.userId).find(
    (x) => x.activityId === a.activityId && x.skuId === a.skuId,
  );
  attempt.value = previous || {
    userId: session.value.userId,
    activityId: a.activityId,
    skuId: a.skuId,
    requestId: crypto.randomUUID(),
    submitted: false,
  };
  remember(attempt.value);
  if (attempt.value.submitted) {
    go(`/request/${attempt.value.requestId}`);
    return;
  }
  captchaOpen.value = true;
  await refreshCaptcha();
}
async function refreshCaptcha(mode: "image" | "accessible" = captchaMode.value) {
  if (!attempt.value || busy.value) return;
  busy.value = true;
  captchaMode.value = mode;
  captcha.value = null;
  answer.value = "";
  captchaError.value = "";
  try {
    captcha.value = await api(
      `/api/seckill/captcha?activityId=${attempt.value.activityId}&skuId=${attempt.value.skuId}&mode=${mode}`,
      session.value,
    );
  } catch (e) {
    captchaError.value = message(e);
  } finally {
    busy.value = false;
  }
}
function toggleCaptchaMode() {
  return refreshCaptcha(captchaMode.value === "image" ? "accessible" : "image");
}
function refreshCurrentCaptcha() {
  return refreshCaptcha(captchaMode.value);
}
async function buy() {
  if (busy.value || !attempt.value || !captcha.value) return;
  const a = attempt.value;
  busy.value = true;
  captchaError.value = "";
  let sent = false;
  try {
    const proof = await api<{ captchaToken: string; activityToken: string }>(
      "/api/seckill/token",
      session.value,
      {
        activityId: a.activityId,
        skuId: a.skuId,
        requestId: a.requestId,
        captchaId: captcha.value.captchaId,
        captchaAnswer: answer.value,
      },
    );
    a.submitted = true;
    remember(a);
    sent = true;
    await api("/api/seckill/buy", session.value, {
      activityId: a.activityId,
      skuId: a.skuId,
      requestId: a.requestId,
      captchaToken: proof.captchaToken,
      activityToken: proof.activityToken,
    });
    captchaOpen.value = false;
    go(`/request/${a.requestId}`);
  } catch (e) {
    if (
      sent &&
      (!(e instanceof ApiError) || e.status === 0 || e.status >= 500)
    ) {
      notice.value = "受理结果尚未确认，正在查询同一笔请求。";
      captchaOpen.value = false;
      go(`/request/${a.requestId}`);
    } else {
      if (sent) {
        a.submitted = false;
        remember(a);
      }
      captchaError.value = message(e);
      captcha.value = null;
    }
  } finally {
    busy.value = false;
  }
}
async function loadOrders() {
  if (!(await requireSession())) return;
  loading.value = true;
  error.value = "";
  try {
    orders.value = (
      await api<{ items: Order[] }>("/api/orders", session.value)
    ).items;
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}
function stopPoll() {
  generation++;
  clearTimeout(timer);
  controller?.abort();
  refreshing.value = false;
}
async function poll(start = Date.now(), delay = 500, version = generation) {
  if (!session.value || version !== generation) return;
  const a = currentAttempt.value;
  const path =
    page.value === "order"
      ? `/api/order/status?orderId=${encodeURIComponent(id.value)}`
      : a
        ? `/api/order/status?activityId=${a.activityId}&skuId=${a.skuId}&requestId=${a.requestId}`
        : "";
  if (!path) {
    pollNote.value = "此浏览器没有保存该请求。请在我的订单中查询。";
    return;
  }
  controller = new AbortController();
  refreshing.value = true;
  try {
    const result = await api<Order>(
      path,
      session.value,
      undefined,
      undefined,
      controller.signal,
    );
    if (version !== generation) return;
    order.value = result;
    pollNote.value = "";
    if (
      result.orderState === "PAID" ||
      result.orderState === "CLOSED" ||
      result.requestState === "FAILED"
    ) {
      refreshing.value = false;
      return;
    }
    if (result.orderId && page.value === "request") {
      go(`/order/${result.orderId}`);
      return;
    }
  } catch (e) {
    if (version !== generation) return;
    if (e instanceof DOMException && e.name === "AbortError") return;
    if (e instanceof ApiError && e.status === 401) {
      saveSession(null);
      session.value = null;
      pollNote.value = "登录已过期，请重新登录后查询。";
      refreshing.value = false;
      return;
    }
    pollNote.value =
      e instanceof ApiError && e.status === 404
        ? "暂未查到结果，正在继续确认；请勿重复提交。"
        : message(e);
  }
  if (version !== generation) return;
  if (Date.now() - start >= 120000) {
    pollNote.value =
      "结果仍在确认中，已暂停自动查询。请求已保留，可稍后继续查询。";
    refreshing.value = false;
    return;
  }
  timer = setTimeout(
    () => poll(start, Math.min(3000, Math.round(delay * 1.3)), version),
    order.value?.orderState === "PENDING_PAYMENT" ? 3000 : delay,
  );
}
function retryPoll() {
  stopPoll();
  pollNote.value = "";
  void poll();
}
async function retryAttempt() {
  const a = currentAttempt.value;
  if (!a || !session.value || busy.value) return;
  attempt.value = a;
  captchaOpen.value = true;
  await refreshCaptcha();
}
async function pay() {
  if (busy.value || !session.value || !order.value?.orderId) return;
  busy.value = true;
  const orderId = order.value.orderId;
  try {
    await api("/api/order/pay", session.value, {
      orderId,
      idempotencyKey: paymentKey(session.value.userId, orderId),
    });
    notice.value = "模拟支付已确认，不会产生真实扣款。";
    retryPoll();
  } catch (e) {
    notice.value = message(e);
    retryPoll();
  } finally {
    busy.value = false;
  }
}
async function loadPage() {
  stopPoll();
  order.value = null;
  pollNote.value = "";
  if (page.value === "product") {
    if (!product.value && id.value) {
      try {
        const result = await api<{ items: Goods[] }>(`/api/goods/${encodeURIComponent(id.value)}`);
        const known = new Set(goods.value.map((g) => g.skuId));
        goods.value = [...goods.value, ...result.items.filter((g) => !known.has(g.skuId))];
      } catch (e) {
        error.value = message(e);
      }
    }
    if (product.value) await loadInfo();
  }
  if (page.value === "orders") await loadOrders();
  if (page.value === "request" || page.value === "order") {
    if (await requireSession()) void poll();
  }
  await nextTick();
  document
    .querySelector<HTMLElement>("main h1")
    ?.focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "instant" });
}
watch(route, () => {
  void loadPage();
  if (page.value === "catalog") {
    void fetchCatalog({ ...catalogQuery.value, category: id.value });
  }
});
watch([authOpen, captchaOpen], async () => {
  await nextTick();
  if (authOpen.value || captchaOpen.value) {
    opener = document.activeElement as HTMLElement;
    dialog.value?.showModal();
    dialog.value?.querySelector<HTMLInputElement>("input")?.focus();
  } else {
    dialog.value?.close();
    opener?.focus();
  }
});
function closeDialog() {
  if (busy.value || authBusy.value) return;
  authOpen.value = false;
  captchaOpen.value = false;
}
function expired() {
  stopPoll();
  saveSession(null);
  session.value = null;
  order.value = null;
  orders.value = [];
  captchaOpen.value = false;
  notice.value = "登录已过期或账号已停用，请重新登录。";
}
onMounted(async () => {
  window.addEventListener("hashchange", hash);
  window.addEventListener("mall-session-expired", expired);
  ticker = setInterval(() => (clock.value = Date.now()), 1000);
  if (session.value) {
    try {
      await api("/api/auth/me", session.value);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        saveSession(null);
        session.value = null;
      }
    }
  }
  await loadCatalog();
  await loadPage();
});
onUnmounted(() => {
  stopPoll();
  clearInterval(ticker);
  window.removeEventListener("hashchange", hash);
  window.removeEventListener("mall-session-expired", expired);
});
</script>

<template>
  <a class="skip" href="#main">跳到主要内容</a>
  <div class="utility-bar">
    <span>SNKR//DROP · ORIGINAL PERFORMANCE</span>
    <div><a href="#/orders">追踪订单</a><a href="#/flash">限时发售</a></div>
  </div>
  <header class="header sports-header">
    <a class="brand sports-brand" href="#/" aria-label="SNKR DROP 首页"
      >SNKR<span>//</span>DROP<i>向前，没有终点。</i></a
    >
    <nav aria-label="主导航">
      <a href="#/" :aria-current="page === 'home' ? 'page' : undefined">首页</a
      ><a
        href="#/catalog"
        :aria-current="page === 'catalog' ? 'page' : undefined"
        >全部鞋款</a
      ><a
        href="#/flash"
        :aria-current="page === 'flash' ? 'page' : undefined"
        class="sale-link"
        >秒杀专区</a
      ><a href="#/orders" :aria-current="page === 'orders' ? 'page' : undefined"
        >我的订单</a
      >
    </nav>
    <div class="account">
      <form class="nav-search" @submit.prevent="go('/catalog')">
        <label class="sr-only" for="nav-search">搜索鞋款</label
        ><input
          id="nav-search"
          v-model="search"
          type="search"
          placeholder="搜索"
        /><button aria-label="搜索鞋款" type="submit">⌕</button>
      </form>
      <a v-if="session?.role === 'ADMIN'" href="#/admin">管理</a
      ><button v-if="!session" class="text-button" @click="openAuth()">
        登录 / 注册</button
      ><button v-else class="text-button" :disabled="busy" @click="logout">
        退出账号</button
      ><button
        class="bag-button"
        aria-label="打开抢购清单"
        @click="bagOpen = true"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          aria-hidden="true"
        >
          <path d="M5 7h14l1 14H4L5 7zM8 9V6a4 4 0 0 1 8 0v3" /></svg
        ><span>{{ bagItems.length }}</span>
      </button>
    </div>
  </header>
  <div class="announcement">
    DROP LIVE <span>·</span> 每人每款限购一双
    <a href="#/flash">查看发售场次 →</a>
  </div>
  <div v-if="notice" class="notice" role="status">
    {{ notice }}<button aria-label="关闭提示" @click="notice = ''">×</button>
  </div>
  <main id="main">
    <ShopFront
      v-if="['home', 'catalog', 'flash'].includes(page)"
      :page="page"
      :goods="goods"
      :catalog-items="catalogItems"
      :catalog-total="catalogTotal"
      :catalog-has-more="catalogHasMore"
      :catalog-loading="catalogLoading"
      :catalog-error="catalogError"
      :activities="activities"
      :loading="loading"
      :error="error"
      :category="page === 'catalog' ? id : ''"
      :initial-search="search"
      @reload="loadCatalog"
      @catalog-change="changeCatalog"
      @catalog-more="loadMoreCatalog"
    />
    <template v-else-if="page === 'product'">
      <div v-if="loading" class="empty" role="status">正在加载鞋款…</div>
      <ShoeDetail
        v-else-if="product"
        :key="product.goodsId"
        :goods="product"
        :variants="goods.filter((g) => g.goodsId === product?.goodsId)"
        :activity="productActivity"
        :can-buy="canBuy"
        :buy-label="buyLabel"
        :countdown="countdown"
        :info-error="infoError"
        :starts-in-future="!!info && clock + offset < Number(info.startsAtMs)"
        :busy="busy"
        @buy="startPurchase"
        @refresh="loadInfo"
        @save="addBag"
        @variant="(sku) => go('/product/' + product!.goodsId + '/' + sku)"
      />
      <div v-else class="empty" role="alert">
        {{ error || "这款鞋暂未上架。"
        }}<button @click="loadCatalog">重新加载</button>
      </div>
    </template>
    <section
      v-else-if="page === 'cart'"
      class="container page-section cart-page"
    >
      <p class="eyebrow">YOUR NEXT ROTATION</p>
      <h1 tabindex="-1">抢购清单</h1>
      <p class="muted">
        逐款确认尺码并验证抢购，生成订单后分别模拟支付。清单不锁定库存。
      </p>
      <div v-if="!bagItems.length" class="empty">
        你的清单还空着。<a href="#/catalog" class="button">探索运动鞋款 →</a>
      </div>
      <div class="cart-layout" v-else>
        <div>
          <article v-for="g in bagItems" :key="g.skuId" class="cart-row">
            <img :src="g.imageUrl" :alt="g.title" />
            <div>
              <h2>{{ g.title }}</h2>
              <p>{{ g.category }} / {{ g.colorway }} / EU {{ g.sizeEu }}</p>
              <p class="muted">数量 1 · 本场每款 SKU 限购一双</p>
              <button class="underlink" @click="removeBag(g.skuId)">
                移除
              </button>
            </div>
            <strong>¥ {{ money(bagPrice(g)) }}</strong
            ><a :href="`#/product/${g.goodsId}/${g.skuId}`" class="button"
              >选择尺码并抢购 →</a
            >
          </article>
        </div>
        <aside class="cart-summary">
          <h2>清单概览</h2>
          <p>{{ bagItems.length }} 双 / {{ bagItems.length }} 笔独立抢购</p>
          <div>
            <span>参考合计</span><strong>¥ {{ money(bagTotal) }}</strong>
          </div>
          <p class="small muted">
            价格、资格和库存以每次服务端校验为准。不支持合单结算或优惠券，不产生真实扣款。
          </p>
          <a href="#/orders" class="button full">查看已生成的订单 →</a>
        </aside>
      </div>
    </section>
    <section v-else-if="page === 'orders'" class="container page-section">
      <p class="eyebrow">YOUR SELECTIONS</p>
      <h1 tabindex="-1">我的订单</h1>
      <p class="muted">每一次喜欢，都有迹可循。</p>
      <div v-if="!session" class="empty">
        <p>登录后查看你的订单。</p>
        <button class="button" @click="openAuth('/orders')">登录账号</button>
      </div>
      <template v-else
        ><div class="order-toolbar">
          <button class="underlink" @click="loadOrders">刷新订单 ↻</button>
        </div>
        <div v-if="loading" class="empty" role="status">正在查询…</div>
        <div v-else-if="error" class="empty error" role="alert">
          {{ error }}
        </div>
        <div v-else-if="!orders.length" class="empty">
          <p>还没有订单，去寻找你的下一双吧。</p>
          <a class="button" href="#/catalog">探索鞋款</a>
        </div>
        <a
          v-for="o in orders"
          :key="o.orderId!"
          class="order-row"
          :href="`#/order/${o.orderId}`"
          ><img
            v-if="goods.find((g) => g.skuId === o.skuId)?.imageUrl"
            :src="goods.find((g) => g.skuId === o.skuId)?.imageUrl"
            alt=""
          />
          <div>
            <h2>
              {{ goods.find((g) => g.skuId === o.skuId)?.title || "活动商品" }}
            </h2>
            <p class="small muted">
              {{ date(o.createdAtMs) }} · {{ o.orderId }}
            </p>
          </div>
          <span :class="['pill', o.orderState === 'PAID' ? 'green' : '']">{{
            stateLabel(o.orderState)
          }}</span
          ><strong>¥ {{ money(o.amountFen) }}</strong
          ><span aria-hidden="true">↗</span></a
        >
        <div
          v-if="attempts(session.userId).some((a) => a.submitted)"
          class="pending-list"
        >
          <h2>抢购请求</h2>
          <p class="small muted">
            网络中断或尚未生成订单时，可从这里继续查询。
          </p>
          <a
            v-for="a in attempts(session.userId).filter((a) => a.submitted)"
            :key="a.requestId"
            :href="`#/request/${a.requestId}`"
            >请求 {{ a.requestId }} <span>查询结果 ↗</span></a
          >
        </div></template
      >
    </section>
    <section
      v-else-if="page === 'order' || page === 'request'"
      class="container page-section"
    >
      <a href="#/orders" class="breadcrumb">← 返回我的订单</a>
      <div class="result">
        <div class="result-symbol" aria-hidden="true">
          {{
            order?.orderState === "PAID"
              ? "✓"
              : order?.orderState === "CLOSED" ||
                  order?.requestState === "FAILED"
                ? "—"
                : "◷"
          }}
        </div>
        <p class="eyebrow">
          {{ page === "request" ? "REQUEST RECEIVED" : "YOUR ORDER" }}
        </p>
        <h1 tabindex="-1">
          {{ stateLabel(order?.orderState || order?.requestState) }}
        </h1>
        <p
          v-if="!order?.orderId && order?.requestState !== 'FAILED'"
          class="muted"
        >
          我们正在确认这笔抢购，请保留页面或稍后从我的订单继续查询。
        </p>
        <p v-if="order?.requestState === 'FAILED'" class="muted">
          {{
            "本次请求未生成订单，库存恢复由服务端处理。请返回鞋款页面查看其他活动。"
          }}
        </p>
        <p v-if="order?.orderState === 'CLOSED'" class="muted">
          本笔订单已关闭，不能继续支付。
        </p>
        <dl>
          <template v-if="order?.orderId"
            ><dt>订单编号</dt>
            <dd>{{ order.orderId }}</dd>
            <dt>订单金额</dt>
            <dd class="result-price">
              ¥ {{ money(order.amountFen) }}
            </dd></template
          ><template v-else
            ><dt>请求编号</dt>
            <dd>{{ id }}</dd></template
          ><template v-if="order?.orderState === 'PENDING_PAYMENT'"
            ><dt>支付截止</dt>
            <dd>{{ date(order.expiresAtMs) }}</dd></template
          >
        </dl>
        <p v-if="pollNote" class="muted" role="status">{{ pollNote }}</p>
        <p v-if="refreshing" class="small muted" role="status">正在自动查询…</p>
        <button
          v-if="order?.orderState === 'PENDING_PAYMENT'"
          class="button"
          :disabled="busy"
          @click="pay"
        >
          {{ busy ? "确认支付结果…" : "模拟支付" }} · ¥
          {{ money(order.amountFen) }}
        </button>
        <p
          v-if="
            order?.orderState === 'PENDING_PAYMENT' ||
            order?.orderState === 'PAID'
          "
          class="small muted"
        >
          演示支付（MOCK），不会产生真实扣款。
        </p>
        <button
          v-if="!refreshing"
          class="underlink"
          @click="session ? retryPoll() : openAuth(route)"
        >
          继续查询 ↻</button
        ><button
          v-if="
            page === 'request' &&
            !order?.orderId &&
            !refreshing &&
            currentAttempt &&
            session
          "
          class="underlink"
          @click="retryAttempt"
        >
          重新验证同一请求</button
        ><a class="underlink" href="#/catalog">继续浏览鞋款 ↗</a>
      </div>
    </section>
    <Admin
      v-else-if="page === 'admin' && session?.role === 'ADMIN'"
      :session="session"
      :goods="goods"
      :activities="activities"
      @updated="loadCatalog"
    />
    <section v-else class="container page-section">
      <h1 tabindex="-1">
        {{ page === "admin" ? "需要管理员账号" : "页面未找到" }}
      </h1>
      <p>请确认账号权限或返回首页。</p>
      <button v-if="!session" class="button" @click="openAuth(route)">
        登录账号</button
      ><a v-else class="button" href="#/">返回首页</a>
    </section>
  </main>
  <footer class="footer sports-footer">
    <div class="brand sports-brand">SNKR<span>//</span>DROP</div>
    <p>向前，没有终点。<br /><span>原创运动品牌概念商城 · 演示项目</span></p>
    <div>
      <h3>开始上场</h3>
      <a href="#/catalog">所有鞋款</a><a href="#/flash">限时发售</a>
    </div>
    <div>
      <h3>你的选择</h3>
      <a href="#/cart">抢购清单</a><a href="#/orders">订单查询</a>
    </div>
    <div class="footer-bottom">
      © {{ new Date().getFullYear() }} SNKR//DROP
      <span>MOVE FORWARD. MAKE IT YOURS.</span>
    </div>
  </footer>
  <ShoppingBag
    :open="bagOpen"
    :items="bagItems"
    :activities="activities"
    @close="bagOpen = false"
    @remove="removeBag"
  />
  <dialog
    ref="dialog"
    class="dialog"
    @cancel.prevent="closeDialog"
    aria-labelledby="dialog-title"
  >
    <button
      class="dialog-close"
      aria-label="关闭窗口"
      :disabled="busy || authBusy"
      @click="closeDialog"
    >
      ×</button
    ><template v-if="authOpen"
      ><p class="eyebrow">WELCOME TO SNKR//DROP</p>
      <h2 id="dialog-title">
        {{ register ? "认识你，很高兴。" : "欢迎回到主场。" }}
      </h2>
      <p class="muted">
        {{
          register ? "创建账号，保存每一次喜欢。" : "登录后参与活动、查询订单。"
        }}
      </p>
      <form @submit.prevent="login">
        <label
          >用户名<input
            v-model="username"
            autocomplete="username"
            required
            pattern="[A-Za-z0-9_\x2D]{3,64}"
            minlength="3"
            maxlength="64"
            placeholder="3–64 位字母、数字、下划线" /></label
        ><label
          >密码<input
            v-model="password"
            :autocomplete="register ? 'new-password' : 'current-password'"
            type="password"
            required
            :minlength="register ? 12 : 1"
            :placeholder="register ? '至少 12 个字符' : '请输入密码'"
        /></label>
        <p v-if="authError" class="error" role="alert">{{ authError }}</p>
        <button class="button full" :disabled="authBusy">
          {{ authBusy ? "正在确认…" : register ? "创建并登录" : "登录" }}
        </button>
      </form>
      <button
        class="underlink auth-toggle"
        :disabled="authBusy"
        @click="
          register = !register;
          authError = '';
        "
      >
        {{ register ? "已有账号？去登录" : "第一次来？创建账号" }} ↗
      </button></template
    ><template v-else-if="captchaOpen"
      ><p class="eyebrow">ONE LAST STEP</p>
      <h2 id="dialog-title">确认这一次喜欢。</h2>
      <p class="muted">{{ captchaMode === "image" ? "输入图片里的 6 位数字，完成抢购验证。" : "使用屏幕阅读器读取题目，输入计算结果完成抢购验证。" }}</p>
      <form @submit.prevent="buy">
        <div class="captcha-image">
          <img
            v-if="captcha?.mode === 'image' && captcha.imageDataUrl"
            :src="captcha.imageDataUrl"
            alt="6 位数字验证码"
          /><p v-else-if="captcha?.mode === 'accessible'" class="captcha-prompt" role="status" aria-live="polite">{{ captcha.challengeText }}</p><span v-else>请刷新获取验证码</span
          ><button
            type="button"
            class="text-button"
            :disabled="busy"
            @click="refreshCurrentCaptcha"
          >
            换一张 ↻
          </button>
        </div>
        <button class="underlink auth-toggle" type="button" :disabled="busy" @click="toggleCaptchaMode">
          {{ captchaMode === "image" ? "改用屏幕阅读器友好的文字题" : "改用图片验证码" }}
        </button>
        <p v-if="captcha" class="small muted">
          验证码
          {{
            Math.max(
              0,
              Math.ceil((Number(captcha.expiresAtMs) - clock - offset) / 1000),
            )
          }}
          秒后失效
        </p>
        <label
          >验证码<input
            v-model="answer"
            inputmode="numeric"
            autocomplete="off"
            required
            pattern="[0-9]{1,6}"
            maxlength="6"
            :placeholder="captchaMode === 'image' ? '输入 6 位数字' : '输入计算结果'"
        /></label>
        <p v-if="captchaError" class="error" role="alert">{{ captchaError }}</p>
        <button
          class="button full"
          :disabled="
            busy || !captcha || clock + offset >= Number(captcha.expiresAtMs)
          "
        >
          {{ busy ? "正在提交…" : "验证并抢购" }}
        </button>
      </form>
      <p class="small muted">
        提交成功仅表示已受理，订单需等待系统确认。
      </p></template
    >
  </dialog>
</template>
