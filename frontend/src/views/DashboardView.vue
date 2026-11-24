<template>
  <main class="dashboard">
    <header class="hero">
      <div>
        <p class="eyebrow">Apex Phase 6A</p>
        <h1>Paper Dashboard</h1>
        <p class="subtitle">先做只读总览：账户、持仓、挂单、净值。</p>
      </div>
      <div class="toolbar">
        <label class="select-wrap">
          <span>账户</span>
          <select v-model="selectedAccountId" @change="reload">
            <option
              v-for="account in payload.accounts"
              :key="account.account_id"
              :value="account.account_id"
            >
              {{ account.strategy_key }} · {{ account.stock_codes.join(", ") || "无标的" }}
            </option>
          </select>
        </label>
        <button class="refresh" @click="reload" :disabled="loading">
          {{ loading ? "加载中..." : "刷新" }}
        </button>
      </div>
    </header>

    <section v-if="error" class="panel error-panel">
      {{ error }}
    </section>

    <section v-else-if="!payload.overview" class="panel empty-panel">
      暂无模拟盘账户。请先运行一次 `scripts/run_paper_trade.py` 创建账户。
    </section>

    <template v-else>
      <section class="overview-grid">
        <article class="metric-card">
          <span class="label">总资产</span>
          <strong>{{ money(payload.overview.total_equity) }}</strong>
          <small>账户ID：{{ payload.overview.account_id }}</small>
        </article>
        <article class="metric-card">
          <span class="label">可用现金</span>
          <strong>{{ money(payload.overview.cash) }}</strong>
          <small>初始资金：{{ money(payload.overview.initial_capital) }}</small>
        </article>
        <article class="metric-card">
          <span class="label">持仓市值</span>
          <strong>{{ money(payload.overview.market_value) }}</strong>
          <small>持仓数：{{ payload.overview.position_count }}</small>
        </article>
        <article class="metric-card">
          <span class="label">累计收益</span>
          <strong :class="profitClass(payload.overview.total_profit)">
            {{ signedMoney(payload.overview.total_profit) }}
          </strong>
          <small :class="profitClass(payload.overview.total_profit)">
            {{ signedPct(payload.overview.total_profit_pct) }}
          </small>
        </article>
      </section>

      <section class="content-grid">
        <article class="panel chart-panel">
          <div class="panel-head">
            <div>
              <h2>净值曲线</h2>
              <p>最近 {{ payload.nav.length }} 个交易日</p>
            </div>
            <div class="tag-list">
              <span class="tag">NAV {{ payload.overview.nav.toFixed(4) }}</span>
              <span class="tag">佣金 {{ money(payload.overview.total_commission) }}</span>
            </div>
          </div>
          <div ref="chartRef" class="chart" />
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h2>待执行订单</h2>
              <p>{{ payload.pending_orders.length }} 笔</p>
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>方向</th>
                  <th>代码</th>
                  <th>数量</th>
                  <th>执行日</th>
                  <th>原因</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="payload.pending_orders.length === 0">
                  <td colspan="5" class="empty-cell">无待执行订单</td>
                </tr>
                <tr v-for="order in payload.pending_orders" :key="order.order_id">
                  <td>{{ order.direction }}</td>
                  <td>{{ order.code }}</td>
                  <td>{{ int(order.req_volume) }}</td>
                  <td>{{ order.execute_date ?? "-" }}</td>
                  <td>{{ order.reason || "-" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>

        <article class="panel positions-panel">
          <div class="panel-head">
            <div>
              <h2>当前持仓</h2>
              <p>{{ payload.positions.length }} 只</p>
            </div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>代码</th>
                  <th>份数</th>
                  <th>可卖</th>
                  <th>成本价</th>
                  <th>现价</th>
                  <th>市值</th>
                  <th>浮盈亏</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="payload.positions.length === 0">
                  <td colspan="7" class="empty-cell">无持仓</td>
                </tr>
                <tr v-for="position in payload.positions" :key="position.code">
                  <td>{{ position.code }}</td>
                  <td>{{ int(position.volume) }}</td>
                  <td>{{ int(position.available) }}</td>
                  <td>{{ price(position.cost_price) }}</td>
                  <td>{{ price(position.current_price) }}</td>
                  <td>{{ money(position.market_value) }}</td>
                  <td :class="profitClass(position.profit)">
                    {{ signedMoney(position.profit) }} ({{ signedPct(position.profit_pct) }})
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </template>
  </main>
</template>

<script setup lang="ts">
import * as echarts from "echarts";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import { fetchDashboard } from "../api/dashboard";
import type { DashboardPayload } from "../types";

const payload = ref<DashboardPayload>({
  accounts: [],
  selected_account_id: null,
  overview: null,
  positions: [],
  pending_orders: [],
  nav: [],
});
const selectedAccountId = ref<string>("");
const loading = ref(false);
const error = ref("");
const chartRef = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;

function money(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 2,
  }).format(value);
}

function signedMoney(value: number) {
  const formatted = money(Math.abs(value));
  return value >= 0 ? `+${formatted}` : `-${formatted}`;
}

function signedPct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function price(value: number) {
  return value.toFixed(3);
}

function int(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function profitClass(value: number) {
  if (value > 0) return "profit-up";
  if (value < 0) return "profit-down";
  return "";
}

function renderChart() {
  if (!chartRef.value || !payload.value.nav.length) {
    chart?.clear();
    return;
  }

  if (!chart) {
    chart = echarts.init(chartRef.value);
  }

  chart.setOption({
    tooltip: {
      trigger: "axis",
      valueFormatter(value: number) {
        return money(value);
      },
    },
    grid: {
      left: 32,
      right: 20,
      top: 24,
      bottom: 30,
    },
    xAxis: {
      type: "category",
      data: payload.value.nav.map((item) => item.trade_date),
      axisLabel: {
        color: "#617180",
      },
    },
    yAxis: {
      type: "value",
      axisLabel: {
        color: "#617180",
        formatter(value: number) {
          return `${(value / 10000).toFixed(1)}w`;
        },
      },
      splitLine: {
        lineStyle: {
          color: "#d7e0e6",
        },
      },
    },
    series: [
      {
        type: "line",
        smooth: true,
        data: payload.value.nav.map((item) => item.total_equity),
        symbol: "none",
        lineStyle: {
          width: 3,
          color: "#0f766e",
        },
        areaStyle: {
          color: "rgba(15, 118, 110, 0.12)",
        },
      },
    ],
  });
}

async function reload() {
  loading.value = true;
  error.value = "";
  try {
    const data = await fetchDashboard(selectedAccountId.value || undefined);
    payload.value = data;
    selectedAccountId.value = data.selected_account_id ?? "";
    renderChart();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载 Dashboard 失败";
  } finally {
    loading.value = false;
  }
}

function handleResize() {
  chart?.resize();
}

onMounted(async () => {
  await reload();
  window.addEventListener("resize", handleResize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  chart?.dispose();
  chart = null;
});

watch(
  () => payload.value.nav,
  () => renderChart(),
  { deep: true },
);
</script>

<style scoped>
.dashboard {
  min-height: 100vh;
  padding: 28px;
}

.hero {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 34px;
  line-height: 1.05;
}

.subtitle {
  margin: 10px 0 0;
  color: var(--muted);
}

.toolbar {
  display: flex;
  gap: 12px;
  align-items: end;
}

.select-wrap {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 13px;
}

.select-wrap select {
  min-width: 320px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
}

.refresh {
  padding: 10px 14px;
  border: 0;
  border-radius: 12px;
  background: var(--accent);
  color: white;
  cursor: pointer;
}

.refresh:disabled {
  opacity: 0.6;
  cursor: default;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.metric-card,
.panel {
  background: var(--panel);
  border: 1px solid rgba(20, 33, 43, 0.06);
  border-radius: 20px;
  box-shadow: var(--shadow);
}

.metric-card {
  padding: 18px 20px;
  display: grid;
  gap: 8px;
}

.metric-card .label {
  color: var(--muted);
  font-size: 13px;
}

.metric-card strong {
  font-size: 28px;
  line-height: 1;
}

.metric-card small {
  color: var(--muted);
}

.content-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 16px;
}

.chart-panel {
  grid-column: 1 / 2;
}

.positions-panel {
  grid-column: 1 / 3;
}

.panel {
  padding: 18px 20px;
}

.panel-head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.panel-head h2 {
  margin: 0;
  font-size: 20px;
}

.panel-head p {
  margin: 6px 0 0;
  color: var(--muted);
}

.tag-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.tag {
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--panel-alt);
  color: var(--muted);
  font-size: 12px;
}

.chart {
  width: 100%;
  height: 340px;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: 12px 10px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  font-size: 14px;
}

th {
  color: var(--muted);
  font-weight: 600;
}

.empty-cell {
  color: var(--muted);
  text-align: center;
}

.profit-up {
  color: var(--success);
}

.profit-down {
  color: var(--danger);
}

.error-panel {
  color: var(--danger);
}

.empty-panel,
.error-panel {
  padding: 20px;
}

@media (max-width: 1100px) {
  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid {
    grid-template-columns: 1fr;
  }

  .positions-panel {
    grid-column: auto;
  }
}

@media (max-width: 760px) {
  .dashboard {
    padding: 18px;
  }

  .hero {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .select-wrap select {
    min-width: 0;
    width: 100%;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
