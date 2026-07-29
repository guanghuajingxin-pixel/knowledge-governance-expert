<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()

const crumbs = computed(() => {
  const matched = route.matched.filter((r) => r.meta?.title)
  return matched.map((r) => r.meta!.title as string)
})
</script>

<template>
  <el-breadcrumb separator="/">
    <el-breadcrumb-item v-for="(crumb, i) in crumbs" :key="i">{{ crumb }}</el-breadcrumb-item>
  </el-breadcrumb>
</template>
