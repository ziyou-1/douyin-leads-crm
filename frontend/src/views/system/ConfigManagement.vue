<template>
  <div class="config-management">
    <h2 class="page-title">系统参数配置</h2>

    <!-- 分类Tab -->
    <el-card shadow="never" class="config-card">
      <el-tabs v-model="activeCategory" @tab-click="handleTabChange">
        <el-tab-pane
          v-for="cat in categories"
          :key="cat.value"
          :label="cat.label"
          :name="cat.value"
        >
          <!-- 私信配置：抖音发送账号扫码登录入口 -->
          <div v-if="cat.value === 'dm'" class="qr-login-entry">
            <el-button type="primary" @click="openQrLoginDialog">
              <el-icon style="margin-right: 4px"><Iphone /></el-icon>扫码登录抖音发送账号
            </el-button>
            <span class="qr-login-tip">扫码登录获取Cookie，用于私信真实发送；登录成功后可在「抖音账号」页面分配/管理</span>
          </div>

          <el-form
            v-if="groupedConfigs[cat.value]"
            label-width="220px"
            label-position="right"
            class="config-form"
          >
            <el-form-item
              v-for="item in groupedConfigs[cat.value]"
              :key="item.key"
              :label="item.label"
            >
              <div
                class="config-item"
                :class="{ 'config-item-textarea': item.value_type === 'textarea' }"
              >
                <!-- 数值类型 -->
                <el-input-number
                  v-if="item.value_type === 'int'"
                  v-model.number="editValues[item.key]"
                  :min="0"
                  controls-position="right"
                  style="width: 200px"
                />
                <!-- 浮点型 -->
                <el-input
                  v-else-if="item.value_type === 'float'"
                  v-model="editValues[item.key]"
                  style="width: 200px"
                  placeholder="输入浮点数"
                />
                <!-- 布尔型 -->
                <el-switch
                  v-else-if="item.value_type === 'bool'"
                  v-model="editValues[item.key]"
                  active-value="true"
                  inactive-value="false"
                />
                <!-- JSON -->
                <el-input
                  v-else-if="item.value_type === 'json'"
                  v-model="editValues[item.key]"
                  type="textarea"
                  :rows="2"
                  style="width: 400px"
                />
                <!-- 多行文本 -->
                <el-input
                  v-else-if="item.value_type === 'textarea'"
                  v-model="editValues[item.key]"
                  type="textarea"
                  :autosize="{ minRows: 8, maxRows: 20 }"
                  maxlength="10000"
                  show-word-limit
                  resize="vertical"
                  placeholder="输入评论意向判别 Prompt"
                  class="prompt-editor"
                />
                <!-- 字符串 -->
                <el-input
                  v-else
                  v-model="editValues[item.key]"
                  style="width: 300px"
                  placeholder="输入配置值"
                />

                <!-- 保存按钮 -->
                <el-button
                  type="primary"
                  size="small"
                  :loading="savingKeys[item.key]"
                  :disabled="editValues[item.key] === item.value"
                  @click="handleSave(item)"
                  style="margin-left: 12px"
                >
                  保存
                </el-button>

                <!-- 说明 -->
                <span class="config-desc">{{ item.description }}</span>
              </div>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 扫码登录抖音账号 -->
    <el-dialog
      v-model="qrDialogVisible"
      title="扫码登录抖音发送账号"
      width="420px"
      :close-on-click-modal="false"
      @close="stopQrPolling"
    >
      <div class="qr-login-body">
        <template v-if="qrStatus === 'loading'">
          <el-icon class="is-loading" :size="32"><Loading /></el-icon>
          <p>正在打开登录页...</p>
        </template>
        <template v-else-if="qrStatus === 'pending'">
          <img :src="'data:image/png;base64,' + qrImageBase64" class="qr-image" alt="登录二维码" />
          <p>请使用抖音APP扫码登录</p>
        </template>
        <template v-else-if="qrStatus === 'expired'">
          <p>二维码已过期</p>
          <el-button type="primary" @click="openQrLoginDialog">重新生成</el-button>
        </template>
        <template v-else-if="qrStatus === 'need_verification'">
          <p class="qr-verify-tip">{{ qrVerifyMessage || '抖音检测到异地登录，需要进行安全验证' }}</p>
          <img
            v-if="qrVerifyImage"
            :src="'data:image/png;base64,' + qrVerifyImage"
            class="qr-verify-screenshot"
            alt="验证页面截图"
          />
          <el-input
            v-model="qrVerifyCode"
            placeholder="请输入手机收到的验证码"
            maxlength="8"
            style="margin-top: 12px"
            @keyup.enter="handleSubmitVerifyCode"
          />
          <el-button
            type="primary"
            :loading="qrVerifySubmitting"
            style="margin-top: 12px; width: 100%"
            @click="handleSubmitVerifyCode"
          >
            提交验证码
          </el-button>
          <el-button
            link
            style="margin-top: 4px"
            @click="openQrLoginDialog"
          >
            重新扫码
          </el-button>
        </template>
        <template v-else-if="qrStatus === 'confirmed'">
          <p class="qr-confirmed-tip">扫码登录成功，请填写账号信息后保存</p>
          <el-form label-width="90px" style="width: 100%">
            <el-form-item label="抖音UID" required>
              <el-input v-model="qrAccountForm.douyin_uid" placeholder="请输入抖音UID" />
            </el-form-item>
            <el-form-item label="昵称" required>
              <el-input v-model="qrAccountForm.nickname" placeholder="请输入账号昵称" />
            </el-form-item>
            <el-form-item label="养号">
              <el-switch v-model="qrAccountForm.nurture_enabled" active-text="登录后走10天养号" />
            </el-form-item>
            <el-form-item label="代理IP">
              <el-input v-model="qrAccountForm.proxy_url" placeholder="socks5://user:pass@host:port，可空" />
            </el-form-item>
          </el-form>
        </template>
      </div>
      <template #footer>
        <el-button @click="qrDialogVisible = false">取消</el-button>
        <el-button
          v-if="qrStatus === 'confirmed'"
          type="primary"
          :loading="qrSaving"
          @click="handleSaveQrAccount"
        >
          保存账号
        </el-button>
      </template>
    </el-dialog>

    <!-- 变更日志 -->
    <el-card shadow="never" class="log-card">
      <template #header>
        <div class="log-header">
          <span class="log-title">变更日志</span>
          <el-input
            v-model="logFilterKey"
            placeholder="按配置项key筛选"
            clearable
            style="width: 250px"
            @clear="fetchLogs"
            @keyup.enter="fetchLogs"
          >
            <template #append>
              <el-button @click="fetchLogs">搜索</el-button>
            </template>
          </el-input>
        </div>
      </template>

      <el-table :data="logs" stripe style="width: 100%" v-loading="logsLoading">
        <el-table-column prop="config_key" label="配置项" min-width="180" show-overflow-tooltip />
        <el-table-column prop="old_value" label="旧值" width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag type="info" size="small">{{ row.old_value || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="new_value" label="新值" width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag type="success" size="small">{{ row.new_value }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="changed_by" label="操作人" width="120" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            {{ formatTime(row.changed_at) }}
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="logPage"
          v-model:page-size="logPageSize"
          :total="logTotal"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @size-change="fetchLogs"
          @current-change="fetchLogs"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Iphone, Loading } from '@element-plus/icons-vue'
import type { TabsPaneContext } from 'element-plus'
import { getSystemConfigs, updateSystemConfig, getConfigChangeLogs } from '@/api/system'
import { addAccount, startQrLogin, pollQrLogin, submitQrVerification } from '@/api/douyinAccounts'

// ── 分类定义 ──
const categories = [
  { value: 'quota', label: '配额管理' },
  { value: 'dm', label: '私信配置' },
  { value: 'risk', label: '风控参数' },
  { value: 'crawler', label: '采集配置' },
  { value: 'discovery', label: '发现配置' },
  { value: 'ai', label: 'AI配置' },
]

const activeCategory = ref('quota')
const configs = ref<any[]>([])
const editValues = reactive<Record<string, string>>({})
const savingKeys = reactive<Record<string, boolean>>({})

// ── 变更日志 ──
const logs = ref<any[]>([])
const logsLoading = ref(false)
const logPage = ref(1)
const logPageSize = ref(20)
const logTotal = ref(0)
const logFilterKey = ref('')

// ── 按分类分组 ──
const groupedConfigs = computed(() => {
  const groups: Record<string, any[]> = {}
  for (const c of configs.value) {
    if (!groups[c.category]) groups[c.category] = []
    groups[c.category].push(c)
  }
  return groups
})

// ── 加载配置 ──
async function fetchConfigs() {
  try {
    const res = await getSystemConfigs()
    if (res.code === 200) {
      configs.value = res.data || []
      // 初始化编辑值
      for (const c of configs.value) {
        editValues[c.key] = c.value
      }
    }
  } catch (e) {
    ElMessage.error('加载配置失败')
  }
}

// ── 保存单个配置 ──
async function handleSave(item: any) {
  const key = item.key
  const value = String(editValues[key])

  // 类型校验
  if (item.value_type === 'int' && isNaN(Number(value))) {
    ElMessage.error('请输入有效的整数')
    return
  }
  if (item.value_type === 'float' && isNaN(Number(value))) {
    ElMessage.error('请输入有效的数字')
    return
  }

  savingKeys[key] = true
  try {
    const res: any = await updateSystemConfig(key, value)
    if (res.code === 200) {
      ElMessage.success(`"${item.label}" 已保存`)
      // 更新本地数据
      item.value = value
      await fetchLogs()
    } else {
      ElMessage.error(res.message || '保存失败')
    }
  } catch (e: any) {
    const msg = e?.response?.data?.detail || '保存失败'
    ElMessage.error(msg)
  } finally {
    savingKeys[key] = false
  }
}

// ── 加载变更日志 ──
async function fetchLogs() {
  logsLoading.value = true
  try {
    const params: any = {
      page: logPage.value,
      page_size: logPageSize.value,
    }
    if (logFilterKey.value) params.key = logFilterKey.value

    const res: any = await getConfigChangeLogs(params)
    if (res.code === 200) {
      logs.value = res.data || []
      logTotal.value = res.total || 0
    }
  } catch (e) {
    ElMessage.error('加载变更日志失败')
  } finally {
    logsLoading.value = false
  }
}

function handleTabChange(_tab: TabsPaneContext) {
  // 切换tab时无额外操作，数据已加载
}

// ── 扫码登录抖音发送账号 ──
const qrDialogVisible = ref(false)
const qrStatus = ref<'loading' | 'pending' | 'confirmed' | 'expired' | 'need_verification'>('loading')
const qrSessionId = ref('')
const qrImageBase64 = ref('')
const qrCookieData = ref('')
const qrSaving = ref(false)
const qrAccountForm = reactive({ douyin_uid: '', nickname: '', proxy_url: '', nurture_enabled: false })
const qrVerifyMessage = ref('')
const qrVerifyImage = ref('')
const qrVerifyCode = ref('')
const qrVerifySubmitting = ref(false)
let qrPollTimer: ReturnType<typeof setTimeout> | null = null
let qrPollCancelled = false

function stopQrPolling() {
  qrPollCancelled = true
  if (qrPollTimer) {
    clearTimeout(qrPollTimer)
    qrPollTimer = null
  }
}

function startQrPolling() {
  stopQrPolling()
  qrPollCancelled = false
  // 不用 setInterval：后端单次轮询里可能截图/操作页面耗时超过间隔时长，
  // 上一次还没返回下一次又发出去，会有两个请求同时操作同一个浏览器页面，
  // 互相打断导致状态抖动。改成"等上一次返回后再排下一次"的链式定时器。
  const tick = async () => {
    if (qrPollCancelled) return
    try {
      const res: any = await pollQrLogin(qrSessionId.value)
      if (qrPollCancelled) return
      if (res.code === 200 && res.data) {
        if (res.data.status === 'confirmed') {
          qrCookieData.value = res.data.cookie_data || ''
          qrStatus.value = 'confirmed'
          return
        } else if (res.data.status === 'expired') {
          qrStatus.value = 'expired'
          return
        } else if (res.data.status === 'need_verification') {
          // 触发异地登录二次验证后页面不再变化，靠人工提交验证码推进，暂停轮询
          qrStatus.value = 'need_verification'
          qrVerifyMessage.value = res.data.verify_message || ''
          qrVerifyImage.value = res.data.verify_image_base64 || ''
          return
        } else if (res.data.qr_image_base64) {
          // 抖音端会自动刷新二维码，同步展示最新的，避免用户扫的是已失效的旧码
          qrImageBase64.value = res.data.qr_image_base64
        }
      }
    } catch {
      // 轮询失败忽略，等待下一次
    }
    if (!qrPollCancelled) {
      qrPollTimer = setTimeout(tick, 2000)
    }
  }
  qrPollTimer = setTimeout(tick, 2000)
}

async function openQrLoginDialog() {
  qrDialogVisible.value = true
  qrStatus.value = 'loading'
  qrAccountForm.douyin_uid = ''
  qrAccountForm.nickname = ''
  qrVerifyMessage.value = ''
  qrVerifyImage.value = ''
  qrVerifyCode.value = ''
  try {
    const res: any = await startQrLogin()
    if (res.code === 200 && res.data) {
      qrSessionId.value = res.data.login_session_id
      qrImageBase64.value = res.data.qr_image_base64
      qrStatus.value = 'pending'
      startQrPolling()
    } else {
      ElMessage.error(res.message || '打开登录页失败')
      qrDialogVisible.value = false
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '打开登录页失败')
    qrDialogVisible.value = false
  }
}

async function handleSubmitVerifyCode() {
  if (!qrVerifyCode.value.trim()) {
    ElMessage.warning('请输入验证码')
    return
  }
  qrVerifySubmitting.value = true
  try {
    const res: any = await submitQrVerification(qrSessionId.value, qrVerifyCode.value.trim())
    if (res.code === 200 && res.data) {
      if (res.data.status === 'confirmed') {
        qrCookieData.value = res.data.cookie_data || ''
        qrStatus.value = 'confirmed'
      } else if (res.data.status === 'expired') {
        qrStatus.value = 'expired'
      } else {
        // 仍是need_verification: 验证码可能有误，展示最新提示和截图供重试
        qrVerifyMessage.value = res.data.verify_message || '验证码可能有误，请重试'
        qrVerifyImage.value = res.data.verify_image_base64 || qrVerifyImage.value
        qrVerifyCode.value = ''
      }
    } else {
      ElMessage.error(res.message || '提交验证码失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提交验证码失败')
  } finally {
    qrVerifySubmitting.value = false
  }
}

async function handleSaveQrAccount() {
  if (!qrAccountForm.douyin_uid.trim() || !qrAccountForm.nickname.trim()) {
    ElMessage.warning('请填写抖音UID和昵称')
    return
  }
  qrSaving.value = true
  try {
    const res: any = await addAccount({
      douyin_uid: qrAccountForm.douyin_uid.trim(),
      nickname: qrAccountForm.nickname.trim(),
      cookie_data: qrCookieData.value,
      proxy_url: qrAccountForm.proxy_url,
      nurture_enabled: qrAccountForm.nurture_enabled,
    })
    if (res.code === 200) {
      ElMessage.success('账号已保存，可到「抖音账号」页面查看/分配')
      qrDialogVisible.value = false
    } else {
      ElMessage.error(res.message || '保存失败')
    }
  } finally {
    qrSaving.value = false
  }
}

onUnmounted(() => {
  stopQrPolling()
})

function formatTime(iso: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
  fetchConfigs()
  fetchLogs()
})
</script>

<style scoped lang="scss">
.config-management {
  padding: 0;
}

.page-title {
  margin: 0 0 20px;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.config-card {
  border: none;
  margin-bottom: 20px;

  :deep(.el-card__body) {
    padding: 16px 20px;
  }
}

.config-form {
  :deep(.el-form-item) {
    margin-bottom: 16px;
    border-bottom: 1px solid #f0f0f0;
    padding-bottom: 12px;

    &:last-child {
      border-bottom: none;
    }
  }

  :deep(.el-form-item__label) {
    font-weight: 500;
    color: #303133;
  }
}

.config-item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.config-item-textarea {
  align-items: flex-start;
  width: 100%;
}

.prompt-editor {
  width: min(760px, 100%);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  line-height: 1.6;
}

.config-desc {
  color: #909399;
  font-size: 12px;
  margin-left: 8px;
}

.qr-login-entry {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
}

.qr-login-tip {
  color: #909399;
  font-size: 12px;
}

.qr-login-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  min-height: 200px;
  justify-content: center;
  text-align: center;
}

.qr-image {
  width: 200px;
  height: 200px;
  border: 1px solid #ebeef5;
}

.qr-confirmed-tip {
  color: #67c23a;
}

.qr-verify-tip {
  color: #e6a23c;
  text-align: center;
  line-height: 1.6;
}

.qr-verify-screenshot {
  width: 100%;
  max-height: 260px;
  object-fit: contain;
  border: 1px solid #ebeef5;
}

.log-card {
  border: none;

  :deep(.el-card__header) {
    padding: 16px 20px;
    border-bottom: 1px solid #ebeef5;
  }
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.log-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
