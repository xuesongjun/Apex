<template>
  <DashboardView />
</template>

<script setup lang="ts">
import DashboardView from "./views/DashboardView.vue";
</script>

<style>
:root {
  color-scheme: light;
  --bg: #f4f6f8;
  --panel: #ffffff;
  --panel-alt: #eef2f5;
  --text: #14212b;
  --muted: #617180;
  --line: #d7e0e6;
  --accent: #0f766e;
  --accent-soft: #d9f3ef;
  --danger: #b42318;
  --success: #067647;
  --shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
}

* {
  box-sizing: border-box;
}

html,
body,
#app {
  margin: 0;
  min-height: 100%;
  background: radial-gradient(circle at top left, #fdf7e8 0%, var(--bg) 42%);
  color: var(--text);
  font-family: "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}

button,
input,
select {
  font: inherit;
}
</style>
