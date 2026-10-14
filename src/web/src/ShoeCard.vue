<script setup lang="ts">
import { money, type Goods, type Activity } from "./api";
const props = defineProps<{
  goods: Goods;
  activity?: Activity;
  flash?: boolean;
}>();
function used() {
  const a = props.activity;
  return a?.initialStock
    ? Math.max(
        0,
        Math.min(
          100,
          Math.round(
            ((Number(a.initialStock) - Number(a.availableStock)) /
              Number(a.initialStock)) *
              100,
          ),
        ),
      )
    : 0;
}
</script>
<template>
  <a
    class="product-card sneaker-card"
    :href="`#/product/${goods.goodsId}/${goods.skuId}`"
    ><div class="product-image">
      <img
        v-if="goods.imageUrl"
        :src="goods.imageUrl"
        :alt="goods.title"
        loading="lazy"
        decoding="async"
      /><span v-else>暂无鞋款图片</span
      ><span class="tag" v-if="activity">{{
        activity.status === "ENDED"
          ? "本场结束"
          : activity.status === "READY"
            ? "即将开抢"
            : "限时秒杀"
      }}</span
      ><span class="image-arrow" aria-hidden="true">↗</span>
    </div>
    <div class="card-text">
      <p class="shoe-category">
        {{ goods.category || "运动鞋" }} · {{ goods.colorway || "概念配色" }}
      </p>
      <h3>{{ goods.title }}</h3>
      <div class="shoe-prices">
        <strong>¥ {{ money(activity?.priceFen || goods.priceFen) }}</strong
        ><del v-if="activity && activity.priceFen !== goods.priceFen"
          >¥ {{ money(goods.priceFen) }}</del
        ><span
          v-if="activity && BigInt(activity.priceFen) < BigInt(goods.priceFen)"
          class="saving"
          >{{
            Math.round(
              (1 - Number(activity.priceFen) / Number(goods.priceFen)) * 100,
            )
          }}% OFF</span
        >
      </div>
      <div v-if="flash && activity?.initialStock" class="stock-summary">
        <div>
          <span>订单库存占用 {{ used() }}%</span
          ><span>余 {{ activity.availableStock }} 双</span>
        </div>
        <progress
          :value="used()"
          max="100"
          :aria-label="goods.title + '订单库存占用'"
        ></progress>
      </div>
      <span class="card-action" v-if="flash"
        >查看活动与尺码 <span>→</span></span
      >
    </div></a
  >
</template>
