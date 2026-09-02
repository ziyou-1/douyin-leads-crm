<template>
  <el-dialog
    :model-value="modelValue"
    title="监控配置 · 四档轮询"
    width="1100px"
    destroy-on-close
    @close="$emit('update:modelValue', false)"
  >
    <el-card class="flow-card" shadow="never">
      <div class="tier-row">
        <div class="tier-badge hot">热门</div>
        <span class="interval-tag">每 {{ config.intervals.hot }} 分钟</span>
        <div class="tier-badge normal">普通</div>
        <span class="interval-tag">每 {{ config.intervals.normal }} 分钟</span>
        <div class="tier-badge cold">冷门</div>
        <span class="interval-tag">每 {{ config.intervals.cold }} 分钟</span>
        <div class="tier-badge paused">暂停</div>
        <span class="interval-tag">每 {{ config.intervals.paused }} 分钟</span>
      </div>
      <p class="upgrade-hint">
        升档：单次新增 ≥ {{ config.upgrade_conditions.to_hot }} → 热门；
        冷门单次新增 ≥ {{ config.upgrade_conditions.to_normal_from_cold }} → 普通；
        暂停增量 &gt; {{ config.upgrade_conditions.to_cold_from_paused }} → 冷门。
        降档：热门连续 {{ config.downgrade_conditions.hot_to_normal }} 次无新评论 → 普通；
        普通最多 {{ config.downgrade_conditions.normal_max_polls }} 次 → 冷门；
        冷门最多 {{ config.downgrade_conditions.cold_max_polls }} 次 → 暂停。
      </p>
    </el-card>

    <el-row :gutter="16" style="margin-top: 12px">
      <el-col :md="8">
        <el-form label-position="top">
          <el-form-item label="热门间隔（分钟）">
            <el-input-number v-model="config.intervals.hot" :min="1" :max="9999" />
          </el-form-item>
          <el-form-item label="普通间隔（分钟）">
            <el-input-number v-model="config.intervals.normal" :min="1" :max="9999" />
          </el-form-item>
          <el-form-item label="冷门间隔（分钟）">
            <el-input-number v-model="config.intervals.cold" :min="1" :max="9999" />
          </el-form-item>
          <el-form-item label="暂停间隔（分钟）">
            <el-input-number v-model="config.intervals.paused" :min="1" :max="9999" />
          </el-form-item>
        </el-form>
      </el-col>
      <el-col :md="8">
        <el-form label-position="top">
          <el-form-item label="升至热门（单次新增≥）">
            <el-input-number v-model="config.upgrade_conditions.to_hot" :min="1" :max="9999" />
          </el-form-item>
          <el-form-item label="冷门升普通（单次新增≥）">
            <el-input-number v-model="config.upgrade_conditions.to_normal_from_cold" :min="1" :max="9999" />
          </el-form-item>
          <el-form-item label="暂停回冷门（总增量&gt;）">
            <el-input-number v-model="config.upgrade_conditions.to_cold_from_paused" :min="1" :max="9999" />
          </el-form-item>
        </el-form>
      </el-col>
      <el-col :md="8">
        <el-form label-position="top">
          <el-form-item label="热门降普通（连续无新评论）">
            <el-input-number v-model="config.downgrade_conditions.hot_to_normal" :min="1" :max="9999" />
          </el-form-item>
          <el-form-item label="普通最大查询次数">
            <el-input-number v-model="config.downgrade_conditions.normal_max_polls" :min="1" :max="9999" />
          </el-form-item>
          <el-form-item label="冷门最大查询次数">
            <el-input-number v-model="config.downgrade_conditions.cold_max_polls" :min="1" :max="9999" />
          </el-form-item>
        </el-form>
      </el-col>
    </el-row>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button @click="resetDefaults">恢复默认</el-button>
      <el-button type="primary" :loading="saving" @click="saveAll">保存并立即生效</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getPollingConfig, updatePollingConfig } from '@/api/polling'

const props = defineProps<{ modelValue: boolean }>()
defineEmits<{ 'update:modelValue': [boolean] }>()

const DEFAULT_CONFIG = {
  intervals: { hot: 3, normal: 8, cold: 20, paused: 120 },
  upgrade_conditions: { to_hot: 3, to_normal_from_cold: 3, to_cold_from_paused: 10 },
  downgrade_conditions: { hot_to_normal: 10, normal_max_polls: 20, cold_max_polls: 20 },
}

const config = reactive({
  intervals: { ...DEFAULT_CONFIG.intervals },
  upgrade_conditions: { ...DEFAULT_CONFIG.upgrade_conditions },
  downgrade_conditions: { ...DEFAULT_CONFIG.downgrade_conditions },
})
const saving = ref(false)

async function fetchConfig() {
  const res: any = await getPollingConfig()
  if (res.code !== 200) {
    throw new Error(res.message || '获取轮询配置失败')
  }
  Object.assign(config.intervals, res.data.intervals)
  Object.assign(config.upgrade_conditions, res.data.upgrade_conditions)
  Object.assign(config.downgrade_conditions, res.data.downgrade_conditions)
}

async function saveAll() {
  saving.value = true
  try {
    const res: any = await updatePollingConfig({
      intervals: { ...config.intervals },
      upgrade_conditions: { ...config.upgrade_conditions },
      downgrade_conditions: { ...config.downgrade_conditions },
    })
    if (res.code !== 200) {
      throw new Error(res.message || '保存失败')
    }
    ElMessage.success('已保存，下次扫描立即按新间隔执行')
  } finally {
    saving.value = false
  }
}

async function resetDefaults() {
  Object.assign(config.intervals, DEFAULT_CONFIG.intervals)
  Object.assign(config.upgrade_conditions, DEFAULT_CONFIG.upgrade_conditions)
  Object.assign(config.downgrade_conditions, DEFAULT_CONFIG.downgrade_conditions)
  await saveAll()
}

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      await fetchConfig()
    }
  },
)
</script>

<style scoped>
.tier-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.tier-badge {
  min-width: 48px;
  height: 28px;
  border-radius: 6px;
  color: #fff;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.tier-badge.hot { background: #f56c6c; }
.tier-badge.normal { background: #e6a23c; }
.tier-badge.cold { background: #409eff; }
.tier-badge.paused { background: #909399; }
.interval-tag { color: #606266; font-size: 13px; margin-right: 8px; }
.upgrade-hint { margin: 12px 0 0; color: #606266; font-size: 13px; line-height: 1.6; }
</style>
