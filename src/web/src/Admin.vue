<script setup lang="ts">
import { onMounted, reactive, ref, watch } from "vue";
import {
  api,
  date,
  money,
  message,
  type Session,
  type Goods,
  type Activity,
} from "./api";
const props = defineProps<{
    session: Session;
    goods: Goods[];
    activities: Activity[];
  }>(),
  emit = defineEmits<{ updated: [] }>();
const tab = ref("goods"),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  rows = ref<Record<string, unknown>[]>([]),
  metrics = ref<Record<string, unknown>>({}),
  editing = ref(""),
  enabled = ref(true);
const goodsForm = reactive({
    title: "",
    description: "",
    imageUrl: "/assets/shoe-run-v1.png",
    priceFen: "",
    stock: "",
  }),
  activityForm = reactive({
    name: "",
    skuId: "",
    stock: "",
    priceFen: "",
    starts: "",
    ends: "",
  });
const adminGoods = ref<(Goods & { enabled: unknown })[]>([]);
const attrs = reactive({ skuId: "", sizeEu: "", category: "", colorway: "" });
async function saveAttrs() {
  if (
    await action(
      "/api/admin/skus/" + attrs.skuId,
      {
        sizeEu: attrs.sizeEu,
        category: attrs.category,
        colorway: attrs.colorway,
      },
      "PATCH",
    )
  )
    await load();
}
async function load() {
  error.value = "";
  rows.value = [];
  metrics.value = {};
  if (tab.value === "activities") return;
  busy.value = true;
  try {
    if (tab.value === "goods") {
      adminGoods.value = (
        await api<{ items: (Goods & { enabled: unknown })[] }>(
          "/api/admin/goods",
          props.session,
        )
      ).items;
    } else {
      const result = await api<{
        items: Record<string, unknown>[];
        metrics?: Record<string, unknown>;
      }>(`/api/admin/${tab.value}`, props.session);
      rows.value = result.items;
      metrics.value = result.metrics || {};
    }
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
async function action(path: string, body?: unknown, method = "POST") {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await api(path, props.session, body, method);
    success.value = "操作已确认。";
    emit("updated");
    return true;
  } catch (e) {
    error.value = message(e);
    return false;
  } finally {
    busy.value = false;
  }
}
async function createGoods() {
  if (
    await action(
      editing.value ? `/api/admin/goods/${editing.value}` : "/api/admin/goods",
      editing.value
        ? {
            title: goodsForm.title,
            description: goodsForm.description,
            imageUrl: goodsForm.imageUrl,
            enabled: enabled.value,
          }
        : { ...goodsForm },
      editing.value ? "PATCH" : "POST",
    )
  ) {
    editing.value = "";
    goodsForm.title = "";
    goodsForm.description = "";
    goodsForm.priceFen = "";
    goodsForm.stock = "";
    await load();
  }
}
function edit(g: Goods & { enabled: unknown }) {
  editing.value = g.goodsId;
  goodsForm.title = g.title;
  goodsForm.description = g.description;
  goodsForm.imageUrl = g.imageUrl;
  enabled.value = isEnabled(g.enabled);
  window.scrollTo({ top: 150, behavior: "smooth" });
}
async function createActivity() {
  const { starts, ends, ...rest } = activityForm;
  const start = Date.parse(starts),
    end = Date.parse(ends);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    error.value = "请填写有效的开始和结束时间。";
    return;
  }
  if (
    await action("/api/admin/activities", {
      ...rest,
      startsAtMs: String(start),
      endsAtMs: String(end),
    })
  ) {
    activityForm.name = "";
    activityForm.stock = "";
  }
}
async function toggleUser(row: Record<string, unknown>) {
  if (
    await action(
      `/api/admin/users/${row.userId}`,
      { enabled: !isEnabled(row.enabled) },
      "PATCH",
    )
  )
    await load();
}
function isEnabled(value: unknown) {
  return value === true || value === 1 || value === "1";
}
watch(tab, load);
onMounted(load);
const labels: Record<string, string> = {
  userId: "用户编号",
  username: "用户名",
  role: "角色",
  enabled: "启用状态",
  createdAtMs: "创建时间",
  orderId: "订单编号",
  orderState: "订单状态",
  amountFen: "金额",
  messageHash: "消息摘要",
  status: "恢复状态",
  attempts: "尝试次数",
  reason: "原因",
  updatedAtMs: "更新时间",
  received: "接收消息",
  confirmed: "订单确认",
  failed: "终止失败",
  outboxPending: "待同步事件",
  compensating: "补偿中",
  quarantined: "隔离记录",
  lastWorkerError: "最近后台错误",
};
function display(key: string, value: unknown) {
  if (key === "amountFen") return "¥ " + money(String(value));
  if (key.endsWith("AtMs")) return date(String(value));
  if (key === "enabled") return isEnabled(value) ? "启用" : "停用";
  if (key === "role") return value === "ADMIN" ? "管理员" : "用户";
  if (key === "orderState")
    return (
      { PAID: "已支付", PENDING_PAYMENT: "待支付", CLOSED: "已关闭" }[
        String(value)
      ] || String(value)
    );
  return value == null ? "—" : value === "NONE" ? "暂无" : String(value);
}
</script>
<template>
  <section class="container page-section admin">
    <p class="eyebrow">STORE MANAGEMENT</p>
    <h1 tabindex="-1">商城管理</h1>
    <p class="muted">商品、活动与订单，清晰有序。</p>
    <nav class="tabs" aria-label="管理分类">
      <button
        v-for="t in [
          { id: 'goods', name: '商品' },
          { id: 'activities', name: '活动' },
          { id: 'users', name: '用户' },
          { id: 'orders', name: '订单' },
          { id: 'recovery', name: '恢复处理' },
        ]"
        :key="t.id"
        :aria-pressed="tab === t.id"
        :disabled="busy"
        @click="tab = t.id"
      >
        {{ t.name }}
      </button>
    </nav>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="success" class="success" role="status">{{ success }}</p>
    <template v-if="tab === 'goods'"
      ><details class="admin-attributes">
        <summary>维护鞋款尺码与运动属性</summary>
        <form class="admin-form" @submit.prevent="saveAttrs">
          <label
            >属性 SKU<select
              v-model="attrs.skuId"
              required
              @change="
                () => {
                  const g = adminGoods.find((x) => x.skuId === attrs.skuId);
                  attrs.sizeEu = g?.sizeEu || '';
                  attrs.category = g?.category || '';
                  attrs.colorway = g?.colorway || '';
                }
              "
            >
              <option value="" disabled>选择鞋款</option>
              <option v-for="g in adminGoods" :key="g.skuId" :value="g.skuId">
                {{ g.title }} · {{ g.skuId }}
              </option>
            </select></label
          >
          <div class="form-grid">
            <label
              >EU 尺码<input
                v-model="attrs.sizeEu"
                placeholder="例如 42 或 38.5" /></label
            ><label
              >运动类别<select v-model="attrs.category">
                <option value="">未分类</option>
                <option v-for="c in ['跑步', '篮球', '休闲', '训练']" :key="c">
                  {{ c }}
                </option>
              </select></label
            >
          </div>
          <label>配色<input v-model="attrs.colorway" maxlength="64" /></label
          ><button class="button" :disabled="busy">保存鞋款属性</button>
          <p class="small muted">
            请在分配活动库存前维护尺码；已参与活动的 SKU
            规格锁定。此操作不改变库存或价格。
          </p>
        </form>
      </details>
      <form class="admin-form" @submit.prevent="createGoods">
        <h2>{{ editing ? "编辑商品" : "上架一款新鞋" }}</h2>
        <label
          >商品名称<input
            v-model="goodsForm.title"
            required
            maxlength="200" /></label
        ><label
          >商品说明<textarea
            v-model="goodsForm.description"
            maxlength="10000"
            rows="3"
          ></textarea></label
        ><label
          >图片路径<input
            v-model="goodsForm.imageUrl"
            pattern="/assets/.*"
            placeholder="/assets/shoe-run-v1.png"
        /></label>
        <div v-if="!editing" class="form-grid">
          <label
            >价格（分）<input
              v-model="goodsForm.priceFen"
              inputmode="numeric"
              pattern="[1-9][0-9]*"
              required /></label
          ><label
            >总库存<input
              v-model="goodsForm.stock"
              inputmode="numeric"
              pattern="[1-9][0-9]*"
              required
          /></label>
        </div>
        <label v-else class="checkbox"
          ><input v-model="enabled" type="checkbox" />在商城展示</label
        >
        <div class="form-actions">
          <button class="button" :disabled="busy">
            {{ busy ? "正在提交…" : editing ? "保存商品" : "创建商品" }}</button
          ><button
            v-if="editing"
            type="button"
            class="underlink"
            @click="editing = ''"
          >
            取消编辑
          </button>
        </div>
      </form>
      <div class="table-scroll">
        <table>
          <caption>
            全部商品，含已下架（接口最多返回 100 条）
          </caption>
          <thead>
            <tr>
              <th>名称</th>
              <th>SKU</th>
              <th>价格</th>
              <th>未分配库存</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="g in adminGoods" :key="g.skuId">
              <td>
                {{ g.title }}
                <small>{{ isEnabled(g.enabled) ? "在售" : "已下架" }}</small>
              </td>
              <td>{{ g.skuId }}</td>
              <td>¥ {{ money(g.priceFen) }}</td>
              <td>{{ g.unallocatedStock }}</td>
              <td>
                <button class="underlink" :disabled="busy" @click="edit(g)">
                  编辑 / 下架
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="small muted">
        下架只隐藏商品。如需停止抢购，请到活动页结束对应活动。已下架商品仍保留在本页，可编辑并重新勾选展示。
      </p></template
    >
    <template v-else-if="tab === 'activities'"
      ><form class="admin-form" @submit.prevent="createActivity">
        <h2>创建限时活动</h2>
        <label
          >活动名称<input
            v-model="activityForm.name"
            required
            maxlength="200" /></label
        ><label
          >商品 SKU<select v-model="activityForm.skuId" required>
            <option disabled value="">选择商品</option>
            <option v-for="g in goods" :key="g.skuId" :value="g.skuId">
              {{ g.title }} · {{ g.skuId }}
            </option>
          </select></label
        >
        <div class="form-grid">
          <label
            >活动库存<input
              v-model="activityForm.stock"
              pattern="[1-9][0-9]*"
              inputmode="numeric"
              required /></label
          ><label
            >活动价（分）<input
              v-model="activityForm.priceFen"
              pattern="[1-9][0-9]*"
              inputmode="numeric"
              required /></label
          ><label
            >开始时间<input
              v-model="activityForm.starts"
              type="datetime-local"
              required /></label
          ><label
            >结束时间<input
              v-model="activityForm.ends"
              type="datetime-local"
              required
          /></label>
        </div>
        <p class="small muted">
          库存从商品未分配库存划拨；创建后还需开启活动，时间使用本地时区。
        </p>
        <button class="button" :disabled="busy">创建活动</button>
      </form>
      <div class="table-scroll">
        <table>
          <caption>
            活动列表（接口最多返回 100 条）
          </caption>
          <thead>
            <tr>
              <th>活动 / 商品</th>
              <th>时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in activities" :key="a.activityId + '-' + a.skuId">
              <td>
                {{ a.name }}<br /><small
                  >{{ a.title }} · {{ a.activityId }}</small
                >
              </td>
              <td>{{ date(a.startsAtMs) }}<br />{{ date(a.endsAtMs) }}</td>
              <td>
                {{
                  { READY: "待开启", ACTIVE: "已开启", ENDED: "已结束" }[
                    a.status
                  ] || a.status
                }}
              </td>
              <td>
                <button
                  v-if="a.status === 'READY'"
                  class="underlink"
                  :disabled="busy"
                  @click="
                    action(`/api/admin/activities/${a.activityId}/activate`, {
                      skuId: a.skuId,
                    })
                  "
                >
                  开启活动</button
                ><button
                  v-if="a.status !== 'ENDED'"
                  class="underlink danger"
                  :disabled="busy"
                  @click="
                    action(`/api/admin/activities/${a.activityId}/end`, {
                      skuId: a.skuId,
                    })
                  "
                >
                  结束活动
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div></template
    >
    <template v-else
      ><div class="order-toolbar">
        <button class="underlink" :disabled="busy" @click="load">刷新 ↻</button
        ><button
          v-if="tab === 'recovery'"
          class="button"
          :disabled="busy"
          @click="action('/api/admin/recovery/run').then(load)"
        >
          执行一轮恢复
        </button>
      </div>
      <div v-if="busy" role="status">正在处理…</div>
      <div v-if="tab === 'recovery'" class="metric-grid">
        <div v-for="(value, key) in metrics" :key="key">
          <span>{{ labels[key] || key }}</span
          ><strong>{{ display(key, value) }}</strong>
        </div>
      </div>
      <div v-if="!rows.length && !busy" class="empty">暂无记录。</div>
      <div v-else class="table-scroll">
        <table>
          <caption>
            {{
              tab === "users"
                ? "用户账号"
                : tab === "orders"
                  ? "全站订单"
                  : "消费失败记录"
            }}（接口最多返回 100 条）
          </caption>
          <thead>
            <tr>
              <th v-for="key in Object.keys(rows[0] || {})" :key="key">
                {{ labels[key] || key }}
              </th>
              <th v-if="tab !== 'orders'">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in rows" :key="i">
              <td v-for="(value, key) in row" :key="key">
                {{ display(String(key), value) }}
              </td>
              <td v-if="tab === 'users'">
                <button
                  class="underlink"
                  :disabled="busy || String(row.userId) === session.userId"
                  @click="toggleUser(row)"
                >
                  {{ isEnabled(row.enabled) ? "禁用" : "启用" }}
                </button>
              </td>
              <td v-if="tab === 'recovery'">
                <button
                  class="underlink"
                  :disabled="busy"
                  @click="
                    action(
                      `/api/admin/recovery/${row.messageHash}/replay`,
                    ).then(load)
                  "
                >
                  重新处理
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div></template
    >
  </section>
</template>
