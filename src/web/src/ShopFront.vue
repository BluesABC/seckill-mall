<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import ShoeCard from "./ShoeCard.vue";
import { date, type Goods, type Activity } from "./api";
const props = defineProps<{
  page: string;
  goods: Goods[];
  catalogItems: Goods[];
  catalogTotal: number;
  catalogHasMore: boolean;
  catalogLoading: boolean;
  catalogError: string;
  activities: Activity[];
  loading: boolean;
  error: string;
  category: string;
  initialSearch: string;
}>();
const emit = defineEmits<{
  reload: [];
  "catalog-change": [query: { q: string; category: string; maxPriceFen: string; sort: string }];
  "catalog-more": [];
}>();
const search = ref(props.initialSearch),
  category = ref(props.category || ""),
  sort = ref("featured"),
  maxPrice = ref(""),
  sessionFilter = ref("all");
let catalogTimer: ReturnType<typeof setTimeout> | undefined;
watch(
  () => props.initialSearch,
  (v) => (search.value = v),
);
watch(
  () => props.category,
  (v) => (category.value = v),
);
watch([search, category, sort, maxPrice], () => {
  clearTimeout(catalogTimer);
  catalogTimer = setTimeout(() => emit("catalog-change", {
    q: search.value.trim(),
    category: category.value,
    maxPriceFen: maxPrice.value ? (BigInt(maxPrice.value) * 100n).toString() : "",
    sort: sort.value,
  }), 250);
});
onUnmounted(() => clearTimeout(catalogTimer));
const unique = computed(() =>
  props.goods.filter(
    (g, i, a) => a.findIndex((x) => x.goodsId === g.goodsId) === i,
  ),
);
const items = computed(() => props.catalogItems);
const activity = (g: Goods) =>
  props.activities.find((a) => a.skuId === g.skuId && a.status === "ACTIVE") ||
  props.activities.find((a) => a.skuId === g.skuId && a.status === "READY");
const drops = computed(() =>
  props.activities
    .filter(
      (a) => sessionFilter.value === "all" || a.status === sessionFilter.value,
    )
    .map((a) => ({
      activity: a,
      goods: props.goods.find((g) => g.skuId === a.skuId),
    }))
    .filter((x) => x.goods),
);
</script>
<template>
  <template v-if="page === 'home'"
    ><section class="hero sports-hero">
      <img
        src="/assets/sports-hero-v1.png"
        alt="夜色跑道上加速前进的跑者"
        fetchpriority="high"
      />
      <div class="hero-copy">
        <p class="eyebrow">THE NEXT MOVE IS YOURS.</p>
        <h1 tabindex="-1">把下一步，<br />变成你的主场。</h1>
        <p>从第一公里，到下一次起跳。<br />为每一种热爱，找到属于你的那双。</p>
        <div class="hero-actions">
          <a href="#/flash" class="button">进入秒杀专区 ↗</a
          ><a href="#/catalog" class="button outline-light">探索全部鞋款</a>
        </div>
        <div class="hero-caption">
          SNKR//DROP PERFORMANCE <span>VOL. 01 / 2026</span>
        </div>
      </div>
      <div class="hero-index">01 <span>/ MOVE FORWARD</span></div>
    </section>
    <div class="category-strip container">
      <a
        v-for="(c, i) in ['跑步', '篮球', '休闲', '训练']"
        :key="c"
        :href="`#/catalog/${c}`"
        ><span>0{{ i + 1 }}</span
        ><strong>{{ c }}</strong
        ><span aria-hidden="true">↗</span></a
      >
    </div>
    <section class="collection container">
      <div class="section-title">
        <div>
          <p class="eyebrow">THE DROP / 限时发售</p>
          <h2>好鞋，不等人。</h2>
        </div>
        <a class="underlink" href="#/flash">全部秒杀场次 ↗</a>
      </div>
      <p class="section-intro">
        抢购受理后，订单将异步确认。每人每款 SKU 限购一双。
      </p>
      <div
        v-if="loading"
        class="skeleton-grid"
        aria-label="正在加载鞋款"
        role="status"
      >
        <div v-for="n in 4" :key="n"></div>
      </div>
      <div v-else-if="error" class="empty error" role="alert">
        {{ error }}<button @click="$emit('reload')">重新加载</button>
      </div>
      <div v-else-if="!unique.length" class="empty">新鞋款正在准备中。</div>
      <div v-else class="product-grid">
        <ShoeCard
          v-for="g in unique.slice(0, 4)"
          :key="g.goodsId"
          :goods="g"
          :activity="activity(g)"
          flash
        />
      </div>
    </section>
    <section class="brand-statement">
      <p class="eyebrow">FOR THE LOVE OF MOVEMENT</p>
      <h2>没有标准的起点。<br />只有不断向前的你。</h2>
      <p>运动不只发生在赛场。街角、球场、跑道，都是你的主场。</p>
      <a href="#/catalog" class="button">找到你的下一双 →</a>
    </section>
    <section class="collection container">
      <div class="section-title">
        <div>
          <p class="eyebrow">EVERYDAY ROTATION</p>
          <h2>下一双，穿出你的节奏。</h2>
        </div>
        <a class="underlink" href="#/catalog">所有鞋款 ↗</a>
      </div>
      <div class="product-grid mt-8">
        <ShoeCard v-for="g in unique.slice(0, 4)" :key="g.goodsId" :goods="g" />
      </div></section
  ></template>
  <section
    v-else-if="page === 'catalog'"
    class="catalog-shell container page-section"
  >
    <p class="eyebrow">FIND YOUR NEXT PAIR</p>
    <div class="catalog-title">
      <h1 tabindex="-1">
        运动鞋款 <span>({{ catalogTotal }})</span>
      </h1>
      <label class="sort-label"
        >排列方式<select v-model="sort">
          <option value="featured">精选顺序</option>
          <option value="low">价格从低到高</option>
          <option value="high">价格从高到低</option>
        </select></label
      >
    </div>
    <div class="catalog-layout">
      <aside class="filter-sidebar" aria-label="鞋款筛选">
        <label
          >寻找好物<input
            v-model="search"
            type="search"
            placeholder="搜索鞋款或描述"
        /></label>
        <fieldset>
          <legend>运动场景</legend>
          <label
            v-for="c in ['', '跑步', '篮球', '休闲', '训练']"
            :key="c"
            class="filter-choice"
            ><input
              v-model="category"
              type="radio"
              name="category"
              :value="c"
            />{{ c || "全部鞋款" }}</label
          >
        </fieldset>
        <label
          >价格范围<select v-model="maxPrice">
            <option value="">全部价格</option>
            <option value="500">¥ 500 以下</option>
            <option value="1000">¥ 1,000 以下</option>
          </select></label
        ><button
          class="underlink"
          @click="
            category = '';
            search = '';
            maxPrice = '';
          "
        >
          清除筛选
        </button>
      </aside>
      <div class="catalog-results">
        <div v-if="catalogLoading && !items.length" class="empty" role="status">正在加载鞋款…</div>
        <div v-else-if="catalogError" class="empty error" role="alert">
          {{ catalogError }}<button @click="$emit('reload')">重新加载</button>
        </div>
        <div v-else-if="loading && !items.length" class="empty" role="status">正在加载鞋款…</div>
        <div v-else-if="error && !items.length" class="empty error" role="alert">
          {{ error }}<button @click="$emit('reload')">重新加载</button>
        </div>
        <div v-else-if="!items.length" class="empty">
          暂无符合条件的好物，试试其他关键词。
        </div>
        <div v-else class="product-grid">
          <ShoeCard
            v-for="g in items"
            :key="g.goodsId"
            :goods="g"
            :activity="activity(g)"
          />
        </div>
        <button
          v-if="catalogHasMore"
          class="button load-more"
          :disabled="catalogLoading"
          @click="$emit('catalog-more')"
        >
          {{ catalogLoading ? "正在加载…" : "加载更多鞋款" }}
        </button>
        <p class="small muted">
          已加载 {{ items.length }} / {{ catalogTotal }} 款
        </p>
      </div>
    </div>
  </section>
  <section v-else class="container page-section flash-page">
    <p class="eyebrow">SNKR//DROP EXCLUSIVE</p>
    <h1 tabindex="-1">限时秒杀。现在上场。</h1>
    <p class="muted">
      选择场次，确认尺码，锁定下一双。库存与资格由服务端最终校验。
    </p>
    <div class="session-tabs" aria-label="秒杀场次">
      <button
        v-for="t in [
          { id: 'all', label: '全部场次' },
          { id: 'ACTIVE', label: '已开启' },
          { id: 'READY', label: '即将开抢' },
          { id: 'ENDED', label: '已结束' },
        ]"
        :key="t.id"
        :aria-pressed="sessionFilter === t.id"
        @click="sessionFilter = t.id"
      >
        {{ t.label }}
      </button>
    </div>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <div v-if="!drops.length" class="empty">此场次暂时没有鞋款。</div>
    <div class="flash-grid">
      <div v-for="d in drops" :key="d.activity.activityId">
        <div class="drop-time">
          {{ d.activity.name
          }}<span
            >{{ date(d.activity.startsAtMs) }} —
            {{ date(d.activity.endsAtMs) }}</span
          >
        </div>
        <ShoeCard :goods="d.goods!" :activity="d.activity" flash />
      </div>
    </div>
    <p class="small muted mt-6">
      库存进度为已确认订单占用的数据库快照，受理中的请求可能尚未计入。不要据此推断抢购一定成功。
    </p>
  </section>
</template>
