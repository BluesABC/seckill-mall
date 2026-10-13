<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { money, type Goods, type Activity } from "./api";
const props = defineProps<{
    open: boolean;
    items: Goods[];
    activities: Activity[];
  }>(),
  emit = defineEmits<{ close: []; remove: [string] }>();
const dialog = ref<HTMLDialogElement | null>(null);
let opener: HTMLElement | null = null;
watch(
  () => props.open,
  async (v) => {
    await nextTick();
    if (v) {
      opener = document.activeElement as HTMLElement;
      dialog.value?.showModal();
    } else {
      dialog.value?.close();
      opener?.focus();
    }
  },
);
const price = (g: Goods) =>
  props.activities.find((a) => a.skuId === g.skuId && a.status === "ACTIVE")
    ?.priceFen || g.priceFen;
</script>
<template>
  <dialog
    ref="dialog"
    class="bag-drawer"
    aria-labelledby="bag-title"
    @cancel.prevent="emit('close')"
  >
    <div class="bag-heading">
      <h2 id="bag-title">
        抢购清单 <span>({{ items.length }})</span>
      </h2>
      <button aria-label="关闭抢购清单" @click="emit('close')">×</button>
    </div>
    <p class="small muted">清单仅保存鞋款选择，不预留库存。</p>
    <div v-if="!items.length" class="empty">清单还空着，去选下一双。</div>
    <div v-for="g in items" :key="g.skuId" class="bag-row">
      <img :src="g.imageUrl" :alt="g.title" />
      <div>
        <h3>{{ g.title }}</h3>
        <p>{{ g.colorway }} / EU {{ g.sizeEu || "未设置" }}</p>
        <strong>¥ {{ money(price(g)) }}</strong>
        <p>数量 1 · 秒杀限购</p>
        <button class="underlink" @click="emit('remove', g.skuId)">移除</button>
      </div>
    </div>
    <a href="#/cart" class="button full" @click="emit('close')"
      >查看清单与抢购流程 →</a
    >
  </dialog>
</template>
