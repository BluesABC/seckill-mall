<script setup lang="ts">
import { computed, ref } from "vue";
import { money, date, type Goods, type Activity } from "./api";
const props = defineProps<{
  goods: Goods;
  variants: Goods[];
  activity?: Activity;
  canBuy: boolean;
  buyLabel: string;
  countdown: string;
  infoError: string;
  startsInFuture: boolean;
  busy: boolean;
}>();
defineEmits<{ buy: []; refresh: []; save: []; variant: [string] }>();
const zoom = ref(false),
  sizeChosen = ref(false),
  showGuide = ref(false),
  view = ref("side");
const sizes = computed(() =>
  [
    ...new Set([
      "38.5",
      "39",
      "40",
      "40.5",
      "41",
      "42",
      "42.5",
      "43",
      "44",
      "45",
      ...props.variants.map((g) => g.sizeEu).filter((s): s is string => !!s),
    ]),
  ].sort((a, b) => Number(a) - Number(b)),
);
const variant = (size: string) => props.variants.find((g) => g.sizeEu === size);
function choose(size: string) {
  const g = variant(size);
  if (g) {
    sizeChosen.value = true;
    return g.skuId;
  }
  return "";
}
</script>
<template>
  <section class="container page-section sneaker-detail">
    <a href="#/catalog" class="breadcrumb"
      >运动鞋款 / {{ goods.category || "全部" }} / {{ goods.title }}</a
    >
    <div class="detail">
      <div class="gallery">
        <div class="gallery-thumbs">
          <button
            :aria-pressed="view === 'side'"
            @click="
              view = 'side';
              zoom = false;
            "
            aria-label="完整鞋款图"
          >
            <img :src="goods.imageUrl" alt="" loading="lazy" decoding="async" /></button
          ><button
            :aria-pressed="view === 'detail'"
            @click="
              view = 'detail';
              zoom = true;
            "
            aria-label="查看鞋面细节"
          >
            <img :src="goods.imageUrl" alt="" loading="lazy" decoding="async" />
          </button>
        </div>
        <button
          class="detail-image"
          @click="zoom = !zoom"
          :aria-label="zoom ? '还原商品图片' : '放大查看商品图片'"
        >
          <img
            v-if="goods.imageUrl"
            :src="goods.imageUrl"
            :alt="goods.title"
            fetchpriority="high"
            decoding="async"
            :class="{ zoom }"
          /><span class="zoom-hint">{{ zoom ? "−" : "+" }}</span>
        </button>
      </div>
      <div class="detail-copy">
        <p class="eyebrow">
          {{ goods.category || "运动" }} / PERFORMANCE FOOTWEAR
        </p>
        <h1 tabindex="-1">{{ goods.title }}</h1>
        <p class="muted">{{ goods.colorway || "概念配色" }} · 运动鞋</p>
        <div class="detail-price">
          <span>¥ {{ money(activity?.priceFen || goods.priceFen) }}</span
          ><del v-if="activity && activity.priceFen !== goods.priceFen"
            >¥ {{ money(goods.priceFen) }}</del
          >
        </div>
        <div class="color-selection">
          <img
            :src="goods.imageUrl"
            :alt="goods.colorway || '当前配色'"
            loading="lazy"
            decoding="async"
          /><span>{{ goods.colorway || "当前配色" }}</span>
        </div>
        <div class="size-heading">
          <strong>选择尺码（EU）</strong
          ><button
            class="underlink"
            @click="showGuide = !showGuide"
            :aria-expanded="showGuide"
          >
            尺码说明 ↗
          </button>
        </div>
        <p v-if="showGuide" class="small muted">
          EU
          为欧洲码。此项目采用概念尺码，没有实物测量的脚长表，请勿作为实际购买建议。
        </p>
        <div class="size-grid">
          <button
            v-for="s in sizes"
            :key="s"
            :disabled="!variant(s)"
            :aria-pressed="sizeChosen && goods.sizeEu === s"
            :aria-label="`尺码 ${s}`"
            @click="$emit('variant', choose(s))"
          >
            {{ s }}
          </button>
        </div>
        <p class="size-note" role="status">
          {{
            sizeChosen ? "已选择 EU " + goods.sizeEu : "请先选择已上架的尺码"
          }}
          · 灰色尺码暂未上架
        </p>
        <div v-if="activity" class="activity">
          <div>
            <span class="dot"></span><strong>{{ activity.name }}</strong>
          </div>
          <p>{{ date(activity.startsAtMs) }} — {{ date(activity.endsAtMs) }}</p>
          <div class="countdown">
            <span>{{ startsInFuture ? "距离开始" : "距离结束" }}</span
            ><b>{{ countdown || "—" }}</b>
          </div>
          <p v-if="infoError" class="error" role="alert">{{ infoError }}</p>
          <button class="text-button" @click="$emit('refresh')">
            刷新活动 ↻
          </button>
        </div>
        <button
          class="button buy"
          :disabled="!canBuy || busy || !sizeChosen"
          @click="$emit('buy')"
        >
          {{ !sizeChosen && canBuy ? "选择尺码后抢购" : buyLabel }}
          <span>→</span></button
        ><button
          class="button secondary full"
          :disabled="!sizeChosen || busy"
          @click="$emit('save')"
        >
          加入抢购清单 <span>＋</span>
        </button>
        <p class="small muted">
          限购一双 / SKU。清单不预扣库存，逐款验证后生成订单；仅支持模拟支付。
        </p>
        <details class="shoe-description">
          <summary>鞋款细节与活动规则</summary>
          <p>{{ goods.description }}</p>
          <p>关闭/超时不释放本场购买资格。图片为原创概念图，以页面说明为准。</p>
        </details>
      </div>
    </div>
  </section>
</template>
