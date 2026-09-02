<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">监控管理</h2>
    </div>

    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <!-- Tab 1: 账号监控 -->
      <el-tab-pane label="账号监控" name="account">
        <el-card>
          <template #header>
            <div class="flex-between">
              <div class="toolbar">
                <el-input
                  v-model="searchText"
                  placeholder="搜索昵称/UID"
                  clearable
                  style="width: 200px"
                  @clear="handleSearch"
                  @keyup.enter="handleSearch"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <el-select
                  v-model="statusFilter"
                  placeholder="全部状态"
                  clearable
                  style="width: 140px"
                  @change="handleSearch"
                >
                  <el-option label="运行中" value="active" />
                  <el-option label="已暂停" value="paused" />
                  <el-option label="异常" value="error" />
                </el-select>
                <el-button type="primary" @click="handleSearch">搜索</el-button>
                <el-dropdown
                  :disabled="selectedMonitors.length === 0"
                  @command="handleBatchStatus"
                >
                  <el-button :loading="batchStatusLoading">
                    批量启停
                    <el-icon style="margin-left: 4px"><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="active">批量启动</el-dropdown-item>
                      <el-dropdown-item command="paused">批量暂停</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button
                  :disabled="selectedMonitors.length === 0"
                  @click="openBatchIntervalDialog"
                >
                  设置拉取间隔
                </el-button>
                <el-button type="primary" plain @click="pollingConfigVisible = true">监控配置</el-button>
                <el-button
                  type="danger"
                  plain
                  :disabled="selectedMonitors.length === 0"
                  :loading="batchDeleteLoading"
                  @click="handleBatchDelete"
                >
                  <el-icon style="margin-right: 4px"><Delete /></el-icon>批量删除
                </el-button>
              </div>
              <div class="toolbar-right">
                <el-button type="warning" plain :loading="discoveryLoading" @click="handleRunDiscovery">
                  <el-icon style="margin-right: 4px"><Search /></el-icon>全网发现
                </el-button>
                <el-button type="danger" plain :loading="cleaningLoading" @click="handleRunCleaning">
                  <el-icon style="margin-right: 4px"><Delete /></el-icon>清洗低质
                </el-button>
                <el-upload
                  ref="uploadRef"
                  :show-file-list="false"
                  accept=".csv,.xlsx,.xls"
                  :before-upload="handleBeforeUpload"
                  :http-request="handleBatchImport"
                >
                  <el-button :loading="importLoading">
                    <el-icon style="margin-right: 4px"><Upload /></el-icon>批量导入
                  </el-button>
                </el-upload>
                <el-button type="primary" @click="openCreateDialog">
                  <el-icon style="margin-right: 4px"><Plus /></el-icon>新增监控
                </el-button>
              </div>
            </div>
          </template>

          <el-table
            :data="monitorList"
            stripe
            v-loading="tableLoading"
            style="width: 100%"
            @selection-change="selectedMonitors = $event"
            @sort-change="handleMonitorSort"
          >
            <el-table-column type="selection" width="48" />
            <el-table-column prop="nickname" label="昵称" min-width="120">
              <template #default="{ row }">
                {{ row.nickname || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="douyin_uid" label="抖音UID" min-width="160" show-overflow-tooltip />
            <el-table-column prop="douyin_url" label="链接" min-width="200" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="100">
              <template #default="{ row }">
                <el-tag :type="row.source === 'discovered' ? 'success' : 'info'" size="small">
                  {{ row.source === 'discovered' ? '发现' : '手动' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="total_high_count" label="High数" width="100" sortable="custom">
              <template #default="{ row }">
                <el-button type="primary" link @click.stop="openMonitorStats(row)">
                  {{ row.total_high_count || 0 }}
                </el-button>
              </template>
            </el-table-column>
            <el-table-column prop="poll_interval_min" label="拉取间隔" width="100">
              <template #default="{ row }">
                {{ row.poll_interval_min }} 分钟
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180">
              <template #default="{ row }">
                {{ formatDate(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-switch
                  v-model="row.status"
                  active-value="active"
                  inactive-value="paused"
                  :loading="row._toggleLoading"
                  @change="handleToggle(row)"
                  :disabled="row.status === 'deleted'"
                  style="margin-right: 12px"
                />
                <el-button type="primary" link @click="openEditDialog(row)">编辑</el-button>
                <el-button type="danger" link @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="pagination.page"
              v-model:page-size="pagination.pageSize"
              :total="pagination.total"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next, jumper"
              @size-change="fetchMonitors"
              @current-change="fetchMonitors"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- Tab 2: 全网监控（话题监控） -->
      <el-tab-pane label="全网监控" name="topic">
        <el-card>
          <template #header>
            <div class="flex-between">
              <div class="toolbar">
                <el-input
                  v-model="topicSearchText"
                  placeholder="搜索话题"
                  clearable
                  style="width: 200px"
                  @clear="handleTopicSearch"
                  @keyup.enter="handleTopicSearch"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <el-select
                  v-model="topicStatusFilter"
                  placeholder="全部状态"
                  clearable
                  style="width: 140px"
                  @change="handleTopicSearch"
                >
                  <el-option label="运行中" value="active" />
                  <el-option label="已暂停" value="paused" />
                </el-select>
                <el-button type="primary" @click="handleTopicSearch">搜索</el-button>
                <el-dropdown
                  :disabled="selectedTopicMonitors.length === 0"
                  @command="handleTopicBatchStatus"
                >
                  <el-button :loading="topicBatchStatusLoading">
                    批量启停
                    <el-icon style="margin-left: 4px"><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="active">批量启动</el-dropdown-item>
                      <el-dropdown-item command="paused">批量暂停</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button
                  :disabled="selectedTopicMonitors.length === 0"
                  @click="openTopicBatchIntervalDialog"
                >
                  设置拉取间隔
                </el-button>
                <el-button
                  type="danger"
                  plain
                  :disabled="selectedTopicMonitors.length === 0"
                  :loading="topicBatchDeleteLoading"
                  @click="handleTopicBatchDelete"
                >
                  <el-icon style="margin-right: 4px"><Delete /></el-icon>批量删除
                </el-button>
              </div>
              <div class="toolbar-right">
                <el-button type="primary" @click="openTopicCreateDialog">
                  <el-icon style="margin-right: 4px"><Plus /></el-icon>新增话题
                </el-button>
              </div>
            </div>
          </template>

          <el-table
            :data="topicMonitorList"
            stripe
            v-loading="topicTableLoading"
            style="width: 100%"
            @selection-change="selectedTopicMonitors = $event"
          >
            <el-table-column type="selection" width="48" />
            <el-table-column prop="topic" label="话题" min-width="160" show-overflow-tooltip />
            <el-table-column prop="industry" label="行业" width="120">
              <template #default="{ row }">
                {{ row.industry || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.description || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="poll_interval_min" label="拉取间隔" width="100">
              <template #default="{ row }">
                {{ row.poll_interval_min }} 分钟
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180">
              <template #default="{ row }">
                {{ formatDate(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-switch
                  v-model="row.status"
                  active-value="active"
                  inactive-value="paused"
                  :loading="row._toggleLoading"
                  @change="handleTopicToggle(row)"
                  style="margin-right: 12px"
                />
                <el-button type="primary" link @click="openTopicEditDialog(row)">编辑</el-button>
                <el-button type="danger" link @click="handleTopicDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="topicPagination.page"
              v-model:page-size="topicPagination.pageSize"
              :total="topicPagination.total"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next, jumper"
              @size-change="fetchTopicMonitors"
              @current-change="fetchTopicMonitors"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <!-- Tab 3: 已移出账号 -->
      <el-tab-pane label="已移出账号" name="removed">
        <el-card>
          <template #header>
            <div class="flex-between">
              <div class="toolbar">
                <el-input
                  v-model="removedSearchText"
                  placeholder="搜索昵称/UID"
                  clearable
                  style="width: 200px"
                  @clear="handleRemovedSearch"
                  @keyup.enter="handleRemovedSearch"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <el-button type="primary" @click="handleRemovedSearch">搜索</el-button>
                <el-button
                  type="danger"
                  plain
                  :disabled="selectedRemovedMonitors.length === 0"
                  :loading="removedBatchDeleteLoading"
                  @click="handleRemovedBatchDelete"
                >
                  <el-icon style="margin-right: 4px"><Delete /></el-icon>批量删除
                </el-button>
              </div>
              <div class="toolbar-right">
                <el-button @click="fetchRemovedMonitors">刷新</el-button>
              </div>
            </div>
          </template>

          <el-table
            :data="removedList"
            stripe
            v-loading="removedTableLoading"
            style="width: 100%"
            @selection-change="selectedRemovedMonitors = $event"
          >
            <el-table-column type="selection" width="48" />
            <el-table-column prop="nickname" label="昵称" min-width="120">
              <template #default="{ row }">
                {{ row.nickname || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="douyin_uid" label="抖音UID" min-width="160" show-overflow-tooltip />
            <el-table-column prop="source" label="来源" width="100">
              <template #default="{ row }">
                <el-tag :type="row.source === 'discovered' ? 'success' : 'info'" size="small">
                  {{ row.source === 'discovered' ? '发现' : '手动' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="total_high_count" label="High数" width="80">
              <template #default="{ row }">
                {{ row.total_high_count || 0 }}
              </template>
            </el-table-column>
            <el-table-column prop="last_high_intent_at" label="最后High时间" width="180">
              <template #default="{ row }">
                {{ row.last_high_intent_at ? formatDate(row.last_high_intent_at) : '从未' }}
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180">
              <template #default="{ row }">
                {{ formatDate(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" link @click="handleRestore(row)">恢复</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="removedPagination.page"
              v-model:page-size="removedPagination.pageSize"
              :total="removedPagination.total"
              :page-sizes="[10, 20, 50]"
              layout="total, sizes, prev, pager, next, jumper"
              @size-change="fetchRemovedMonitors"
              @current-change="fetchRemovedMonitors"
            />
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- ===== 账号监控弹窗 ===== -->

    <!-- Create Dialog -->
    <el-dialog v-model="createDialogVisible" title="新增监控" width="500px" destroy-on-close>
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
        <el-form-item label="抖音链接" prop="douyin_url">
          <el-input v-model="createForm.douyin_url" placeholder="输入抖音用户链接或UID" />
        </el-form-item>
        <el-form-item label="拉取间隔" prop="poll_interval_min">
          <el-input-number v-model="createForm.poll_interval_min" :min="1" :max="1440" />
          <span style="margin-left: 8px; color: #909399">分钟</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleCreate">确定</el-button>
      </template>
    </el-dialog>

    <!-- Edit Dialog -->
    <el-dialog v-model="editDialogVisible" title="编辑监控" width="500px" destroy-on-close>
      <el-form ref="editFormRef" :model="editForm" label-width="100px">
        <el-form-item label="昵称">
          <el-input v-model="editForm.nickname" placeholder="请输入昵称" />
        </el-form-item>
        <el-form-item label="拉取间隔">
          <el-input-number v-model="editForm.poll_interval_min" :min="1" :max="1440" />
          <span style="margin-left: 8px; color: #909399">分钟</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleEdit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="batchIntervalDialogVisible"
      title="批量设置拉取间隔 / 意向分级参数"
      width="460px"
      destroy-on-close
    >
      <el-form label-width="140px">
        <el-form-item label="已选择账号">
          <span>{{ selectedMonitors.length }} 个</span>
        </el-form-item>
        <el-form-item label="拉取间隔">
          <el-input-number
            v-model="batchPollInterval"
            :min="1"
            :max="1440"
            controls-position="right"
          />
          <span style="margin-left: 8px; color: #909399">分钟</span>
        </el-form-item>
        <el-form-item label="意向时效窗口">
          <el-input-number
            v-model="batchAiFreshnessMin"
            :min="1"
            :max="1440"
            controls-position="right"
          />
          <span style="margin-left: 8px; color: #909399">分钟内评论才送AI分析</span>
        </el-form-item>
        <el-form-item label="高意向阈值">
          <el-input-number
            v-model="batchHighIntentMin"
            :min="1"
            :max="1440"
            controls-position="right"
          />
          <span style="margin-left: 8px; color: #909399">分钟内为高意向，超过为中意向</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchIntervalDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="batchIntervalLoading"
          @click="handleBatchIntervalSubmit"
        >
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- ===== 全网监控（话题监控）弹窗 ===== -->

    <el-dialog
      v-model="topicBatchIntervalDialogVisible"
      title="批量设置拉取间隔"
      width="420px"
      destroy-on-close
    >
      <el-form label-width="110px">
        <el-form-item label="已选择话题">
          <span>{{ selectedTopicMonitors.length }} 个</span>
        </el-form-item>
        <el-form-item label="拉取间隔">
          <el-input-number
            v-model="topicBatchPollInterval"
            :min="1"
            :max="1440"
            controls-position="right"
          />
          <span style="margin-left: 8px; color: #909399">分钟</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="topicBatchIntervalDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="topicBatchIntervalLoading"
          @click="handleTopicBatchIntervalSubmit"
        >
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- Create Topic Dialog -->
    <el-dialog v-model="topicCreateDialogVisible" title="新增话题监控" width="500px" destroy-on-close>
      <el-form ref="topicCreateFormRef" :model="topicCreateForm" :rules="topicCreateRules" label-width="100px">
        <el-form-item label="话题/行业" prop="topic">
          <el-input v-model="topicCreateForm.topic" placeholder="输入监控话题，如情感挽回、心理咨询" />
        </el-form-item>
        <el-form-item label="行业分类" prop="industry">
          <el-select v-model="topicCreateForm.industry" placeholder="请选择行业（可选）" clearable allow-create filterable style="width: 100%">
            <el-option label="情感咨询" value="情感咨询" />
            <el-option label="心理健康" value="心理健康" />
            <el-option label="教育培训" value="教育培训" />
            <el-option label="医美整形" value="医美整形" />
            <el-option label="法律咨询" value="法律咨询" />
            <el-option label="金融理财" value="金融理财" />
          </el-select>
        </el-form-item>
        <el-form-item label="话题描述" prop="description">
          <el-input
            v-model="topicCreateForm.description"
            type="textarea"
            :rows="3"
            placeholder="可选，帮助舆情API理解采集范围，如：关注情感挽回、恋爱技巧、婚姻修复等方向"
          />
        </el-form-item>
        <el-form-item label="拉取间隔" prop="poll_interval_min">
          <el-input-number v-model="topicCreateForm.poll_interval_min" :min="1" :max="1440" />
          <span style="margin-left: 8px; color: #909399">分钟</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="topicCreateDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="topicSubmitLoading" @click="handleTopicCreate">确定</el-button>
      </template>
    </el-dialog>

    <!-- Edit Topic Dialog -->
    <el-dialog v-model="topicEditDialogVisible" title="编辑话题监控" width="500px" destroy-on-close>
      <el-form ref="topicEditFormRef" :model="topicEditForm" label-width="100px">
        <el-form-item label="话题/行业">
          <el-input v-model="topicEditForm.topic" placeholder="输入监控话题" />
        </el-form-item>
        <el-form-item label="行业分类">
          <el-select v-model="topicEditForm.industry" placeholder="请选择行业（可选）" clearable allow-create filterable style="width: 100%">
            <el-option label="情感咨询" value="情感咨询" />
            <el-option label="心理健康" value="心理健康" />
            <el-option label="教育培训" value="教育培训" />
            <el-option label="医美整形" value="医美整形" />
            <el-option label="法律咨询" value="法律咨询" />
            <el-option label="金融理财" value="金融理财" />
          </el-select>
        </el-form-item>
        <el-form-item label="话题描述">
          <el-input
            v-model="topicEditForm.description"
            type="textarea"
            :rows="3"
            placeholder="可选，帮助舆情API理解采集范围"
          />
        </el-form-item>
        <el-form-item label="拉取间隔">
          <el-input-number v-model="topicEditForm.poll_interval_min" :min="1" :max="1440" />
          <span style="margin-left: 8px; color: #909399">分钟</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="topicEditDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="topicSubmitLoading" @click="handleTopicEdit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="statsDialogVisible"
      :title="`${monitorStats?.monitor.nickname || monitorStats?.monitor.douyin_uid || ''} 统计详情`"
      width="920px"
      destroy-on-close
    >
      <div class="stats-toolbar">
        <el-radio-group v-model="statsDays" @change="fetchMonitorStats">
          <el-radio-button :value="1">一天</el-radio-button>
          <el-radio-button :value="3">三天</el-radio-button>
          <el-radio-button :value="7">一周</el-radio-button>
          <el-radio-button :value="30">一个月</el-radio-button>
        </el-radio-group>
        <el-button type="primary" :loading="statsExporting" @click="handleStatsExport">
          <el-icon style="margin-right: 4px"><Download /></el-icon>导出数据
        </el-button>
      </div>

      <div v-loading="statsLoading">
        <el-row :gutter="12" class="stats-summary">
          <el-col :span="8">
            <div class="summary-item">
              <div class="summary-label">意向评论数</div>
              <div class="summary-value">{{ monitorStats?.high_lead_count || 0 }}</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="summary-item">
              <div class="summary-label">客服私信数</div>
              <div class="summary-value">{{ monitorStats?.outbound_message_count || 0 }}</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="summary-item">
              <div class="summary-label">已沟通线索数</div>
              <div class="summary-value">{{ monitorStats?.communicated_lead_count || 0 }}</div>
            </div>
          </el-col>
        </el-row>

        <h4 class="stats-section-title">客服私信统计</h4>
        <el-table :data="monitorStats?.sales_stats || []" stripe max-height="220">
          <el-table-column prop="username" label="客服" min-width="140" />
          <el-table-column prop="assigned_leads" label="分配线索数" width="130" />
          <el-table-column prop="communicated_leads" label="已沟通线索数" width="140" />
          <el-table-column prop="outbound_messages" label="私信发送数" width="130" />
        </el-table>

        <h4 class="stats-section-title">意向评论明细</h4>
        <el-table :data="monitorStats?.leads || []" stripe max-height="320">
          <el-table-column prop="user_nickname" label="评论用户" width="120" show-overflow-tooltip />
          <el-table-column prop="comment_content" label="评论内容" min-width="220" show-overflow-tooltip />
          <el-table-column prop="comment_time" label="评论时间" width="170">
            <template #default="{ row }">
              {{ row.comment_time ? formatDate(row.comment_time) : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="sales_name" label="分配客服" width="110">
            <template #default="{ row }">{{ row.sales_name || '-' }}</template>
          </el-table-column>
          <el-table-column prop="outbound_messages" label="私信数" width="90" />
        </el-table>
      </div>
    </el-dialog>
    <PollingConfig v-model="pollingConfigVisible" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import PollingConfig from '@/components/PollingConfig.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions, UploadInstance } from 'element-plus'
import { Search, Plus, Upload, Delete, Download, ArrowDown } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import {
  getMonitors, createMonitor, updateMonitor, deleteMonitor,
  batchDeleteMonitors, batchUpdateMonitorStatus, batchUpdateMonitorPollInterval,
  toggleMonitor, batchImport, runDiscovery, runCleaning,
  getRemovedMonitors, restoreMonitor, getMonitorAccountStats, exportMonitorAccountStats,
} from '@/api/monitor'
import type { MonitorItem, MonitorAccountStats } from '@/api/monitor'
import {
  getTopicMonitors, createTopicMonitor, updateTopicMonitor,
  deleteTopicMonitor, batchDeleteTopicMonitors, toggleTopicMonitor,
  batchUpdateTopicMonitorStatus, batchUpdateTopicMonitorPollInterval,
} from '@/api/topicMonitor'
import type { TopicMonitorItem } from '@/api/topicMonitor'

// ── Tab state ──
const activeTab = ref('account')
const pollingConfigVisible = ref(false)

function handleTabChange(tab: string | number) {
  if (tab === 'account') {
    fetchMonitors()
  } else if (tab === 'topic') {
    fetchTopicMonitors()
  } else if (tab === 'removed') {
    fetchRemovedMonitors()
  }
}

// ── 通用工具函数 ──
function formatDate(dateStr: string) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

function statusTagType(status: string) {
  const map: Record<string, string> = { active: 'success', paused: 'warning', deleted: 'danger', error: 'danger', removed: 'info' }
  return map[status] || 'info'
}

function statusLabel(status: string) {
  const map: Record<string, string> = { active: '运行中', paused: '已暂停', deleted: '已删除', error: '异常', removed: '已移出' }
  return map[status] || status
}

// ═══════════════════════════════════════════════════════════════
//  账号监控
// ═══════════════════════════════════════════════════════════════

const monitorList = ref<(MonitorItem & { _toggleLoading?: boolean })[]>([])
const tableLoading = ref(false)
const searchText = ref('')
const statusFilter = ref('')
const pagination = reactive({ page: 1, pageSize: 20, total: 0 })
const selectedMonitors = ref<MonitorItem[]>([])
const batchDeleteLoading = ref(false)
const batchStatusLoading = ref(false)
const batchIntervalDialogVisible = ref(false)
const batchIntervalLoading = ref(false)
const batchPollInterval = ref(5)
const batchAiFreshnessMin = ref(20)
const batchHighIntentMin = ref(8)
const monitorSort = reactive({ sortBy: 'id', sortOrder: 'desc' })

async function fetchMonitors() {
  tableLoading.value = true
  try {
    const res: any = await getMonitors({
      page: pagination.page,
      page_size: pagination.pageSize,
      status: statusFilter.value || undefined,
      search: searchText.value || undefined,
      sort_by: monitorSort.sortBy,
      sort_order: monitorSort.sortOrder,
    })
    if (res.code === 200) {
      monitorList.value = (res.data || []).map((item: MonitorItem) => ({ ...item, _toggleLoading: false }))
      pagination.total = res.total
    }
  } finally {
    tableLoading.value = false
  }
}

function handleSearch() {
  pagination.page = 1
  fetchMonitors()
}

function handleMonitorSort({ prop, order }: { prop: string; order: string | null }) {
  monitorSort.sortBy = order && prop === 'total_high_count' ? 'total_high_count' : 'id'
  monitorSort.sortOrder = order === 'ascending' ? 'asc' : 'desc'
  pagination.page = 1
  fetchMonitors()
}

async function handleBatchStatus(command: 'active' | 'paused') {
  const ids = selectedMonitors.value.map((item) => item.id)
  if (ids.length === 0) return
  const action = command === 'active' ? '启动' : '暂停'
  try {
    await ElMessageBox.confirm(
      `确定要${action}选中的 ${ids.length} 个监控账号吗？`,
      `批量${action}确认`,
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  batchStatusLoading.value = true
  try {
    const res: any = await batchUpdateMonitorStatus(ids, command)
    if (res.code === 200) {
      ElMessage.success(res.message || `批量${action}成功`)
      selectedMonitors.value = []
      fetchMonitors()
    } else {
      ElMessage.error(res.message || `批量${action}失败`)
    }
  } finally {
    batchStatusLoading.value = false
  }
}

function openBatchIntervalDialog() {
  if (selectedMonitors.value.length === 0) return
  const intervals = new Set(selectedMonitors.value.map((item) => item.poll_interval_min))
  batchPollInterval.value = intervals.size === 1
    ? selectedMonitors.value[0].poll_interval_min
    : 5
  const freshnessSet = new Set(selectedMonitors.value.map((item) => item.ai_freshness_min))
  batchAiFreshnessMin.value = freshnessSet.size === 1
    ? selectedMonitors.value[0].ai_freshness_min
    : 20
  const highIntentSet = new Set(selectedMonitors.value.map((item) => item.high_intent_min))
  batchHighIntentMin.value = highIntentSet.size === 1
    ? selectedMonitors.value[0].high_intent_min
    : 8
  batchIntervalDialogVisible.value = true
}

async function handleBatchIntervalSubmit() {
  const ids = selectedMonitors.value.map((item) => item.id)
  if (ids.length === 0) return
  if (batchHighIntentMin.value > batchAiFreshnessMin.value) {
    ElMessage.warning('高意向阈值不能大于意向时效窗口')
    return
  }
  batchIntervalLoading.value = true
  try {
    const res: any = await batchUpdateMonitorPollInterval(ids, {
      poll_interval_min: batchPollInterval.value,
      ai_freshness_min: batchAiFreshnessMin.value,
      high_intent_min: batchHighIntentMin.value,
    })
    if (res.code === 200) {
      ElMessage.success(res.message || '批量设置成功')
      batchIntervalDialogVisible.value = false
      selectedMonitors.value = []
      fetchMonitors()
    } else {
      ElMessage.error(res.message || '批量设置失败')
    }
  } finally {
    batchIntervalLoading.value = false
  }
}

const statsDialogVisible = ref(false)
const statsLoading = ref(false)
const statsExporting = ref(false)
const statsDays = ref(7)
const statsMonitorId = ref<number>()
const monitorStats = ref<MonitorAccountStats | null>(null)

async function openMonitorStats(row: MonitorItem) {
  statsMonitorId.value = row.id
  statsDays.value = 7
  monitorStats.value = null
  statsDialogVisible.value = true
  await fetchMonitorStats()
}

async function fetchMonitorStats() {
  if (!statsMonitorId.value) return
  statsLoading.value = true
  try {
    const res: any = await getMonitorAccountStats(statsMonitorId.value, statsDays.value)
    if (res.code === 200) {
      monitorStats.value = res.data
    }
  } finally {
    statsLoading.value = false
  }
}

async function handleStatsExport() {
  if (!statsMonitorId.value) return
  statsExporting.value = true
  try {
    const data = await exportMonitorAccountStats(statsMonitorId.value, statsDays.value)
    const url = window.URL.createObjectURL(new Blob([data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `monitor_stats_${statsMonitorId.value}_${statsDays.value}days.xlsx`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } finally {
    statsExporting.value = false
  }
}

// ── Create dialog ──
const createDialogVisible = ref(false)
const createFormRef = ref<FormInstance>()
const submitLoading = ref(false)

const createForm = reactive({ douyin_url: '', poll_interval_min: 5 })
const createRules: FormRules = {
  douyin_url: [{ required: true, message: '请输入抖音链接或UID', trigger: 'blur' }],
  poll_interval_min: [{ required: true, message: '请输入拉取间隔', trigger: 'blur' }],
}

function openCreateDialog() {
  createForm.douyin_url = ''
  createForm.poll_interval_min = 5
  createDialogVisible.value = true
}

async function handleCreate() {
  if (!createFormRef.value) return
  const valid = await createFormRef.value.validate().catch(() => false)
  if (!valid) return
  submitLoading.value = true
  try {
    const res: any = await createMonitor(createForm)
    if (res.code === 200) {
      ElMessage.success('监控创建成功')
      createDialogVisible.value = false
      fetchMonitors()
    } else {
      ElMessage.error(res.message || '创建失败')
    }
  } finally {
    submitLoading.value = false
  }
}

// ── Edit dialog ──
const editDialogVisible = ref(false)
const editFormRef = ref<FormInstance>()
const editForm = reactive({ id: 0, nickname: '', poll_interval_min: 5 })

function openEditDialog(row: MonitorItem) {
  editForm.id = row.id
  editForm.nickname = row.nickname
  editForm.poll_interval_min = row.poll_interval_min
  editDialogVisible.value = true
}

async function handleEdit() {
  submitLoading.value = true
  try {
    const res: any = await updateMonitor(editForm.id, {
      nickname: editForm.nickname,
      poll_interval_min: editForm.poll_interval_min,
    })
    if (res.code === 200) {
      ElMessage.success('更新成功')
      editDialogVisible.value = false
      fetchMonitors()
    } else {
      ElMessage.error(res.message || '更新失败')
    }
  } finally {
    submitLoading.value = false
  }
}

// ── Toggle ──
async function handleToggle(row: MonitorItem & { _toggleLoading?: boolean }) {
  row._toggleLoading = true
  try {
    const res: any = await toggleMonitor(row.id)
    if (res.code === 200) {
      ElMessage.success(res.data?.status === 'active' ? '已启动' : '已暂停')
      fetchMonitors()
    } else {
      ElMessage.error(res.message || '操作失败')
      fetchMonitors()
    }
  } catch {
    fetchMonitors()
  } finally {
    row._toggleLoading = false
  }
}

// ── Delete ──
async function handleDelete(row: MonitorItem) {
  try {
    await ElMessageBox.confirm(`确定要删除该监控账号吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  submitLoading.value = true
  try {
    const res: any = await deleteMonitor(row.id)
    if (res.code === 200) {
      ElMessage.success('删除成功')
      fetchMonitors()
    } else {
      ElMessage.error(res.message || '删除失败')
    }
  } finally {
    submitLoading.value = false
  }
}

async function handleBatchDelete() {
  const ids = selectedMonitors.value.map((item) => item.id)
  if (ids.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${ids.length} 个监控账号吗？`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  batchDeleteLoading.value = true
  try {
    const res: any = await batchDeleteMonitors(ids)
    if (res.code === 200) {
      ElMessage.success(res.message || '批量删除成功')
      if (ids.length === monitorList.value.length && pagination.page > 1) {
        pagination.page -= 1
      }
      selectedMonitors.value = []
      fetchMonitors()
    } else {
      ElMessage.error(res.message || '批量删除失败')
    }
  } finally {
    batchDeleteLoading.value = false
  }
}

// ── Batch import ──
const uploadRef = ref<UploadInstance>()
const importLoading = ref(false)

function handleBeforeUpload(file: File) {
  const allowed = ['.csv', '.xlsx', '.xls']
  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase()
  if (!allowed.includes(ext)) {
    ElMessage.error('仅支持 .csv、.xlsx 和 .xls 格式')
    return false
  }
  return true
}

async function handleBatchImport(options: UploadRequestOptions) {
  importLoading.value = true
  try {
    const res: any = await batchImport(options.file)
    if (res.code === 200) {
      if (res.data?.success_count === 0 && res.data?.fail_count > 0) {
        ElMessage.error(res.data?.errors?.[0] || res.message || '导入失败')
      } else {
        ElMessage.success(res.message || '导入完成')
      }
      fetchMonitors()
    } else {
      ElMessage.error(res.message || '导入失败')
    }
  } catch {
    ElMessage.error('导入失败')
  } finally {
    importLoading.value = false
  }
}

// ── 全网发现 & 清洗 ──
const discoveryLoading = ref(false)
const cleaningLoading = ref(false)

async function handleRunDiscovery() {
  try {
    await ElMessageBox.confirm(
      '全网发现是高成本操作，将在后台异步执行。确认开始？',
      '全网发现',
      { type: 'warning', confirmButtonText: '开始', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  discoveryLoading.value = true
  try {
    const res: any = await runDiscovery()
    if (res.code === 200) {
      ElMessage.success(res.message || '全网发现任务已提交')
    } else {
      ElMessage.error(res.message || '提交失败')
    }
  } catch {
    ElMessage.error('提交失败')
  } finally {
    discoveryLoading.value = false
  }
}

async function handleRunCleaning() {
  try {
    await ElMessageBox.confirm(
      '将清洗超过14天无high评论的账号，此操作可恢复。确认执行？',
      '账号清洗',
      { type: 'warning', confirmButtonText: '执行', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  cleaningLoading.value = true
  try {
    const res: any = await runCleaning()
    if (res.code === 200) {
      ElMessage.success(res.message || '清洗任务已提交')
    } else {
      ElMessage.error(res.message || '提交失败')
    }
  } catch {
    ElMessage.error('提交失败')
  } finally {
    cleaningLoading.value = false
  }
}

// ═══════════════════════════════════════════════════════════════
//  全网监控（话题监控）
// ═══════════════════════════════════════════════════════════════

const topicMonitorList = ref<(TopicMonitorItem & { _toggleLoading?: boolean })[]>([])
const topicTableLoading = ref(false)
const topicSearchText = ref('')
const topicStatusFilter = ref('')
const topicPagination = reactive({ page: 1, pageSize: 20, total: 0 })
const selectedTopicMonitors = ref<TopicMonitorItem[]>([])
const topicBatchDeleteLoading = ref(false)
const topicBatchStatusLoading = ref(false)
const topicBatchIntervalDialogVisible = ref(false)
const topicBatchIntervalLoading = ref(false)
const topicBatchPollInterval = ref(5)

async function fetchTopicMonitors() {
  topicTableLoading.value = true
  try {
    const res: any = await getTopicMonitors({
      page: topicPagination.page,
      page_size: topicPagination.pageSize,
      status: topicStatusFilter.value || undefined,
      search: topicSearchText.value || undefined,
    })
    if (res.code === 200) {
      topicMonitorList.value = (res.data || []).map((item: TopicMonitorItem) => ({ ...item, _toggleLoading: false }))
      topicPagination.total = res.total
    }
  } finally {
    topicTableLoading.value = false
  }
}

function handleTopicSearch() {
  topicPagination.page = 1
  fetchTopicMonitors()
}

async function handleTopicBatchStatus(command: 'active' | 'paused') {
  const ids = selectedTopicMonitors.value.map((item) => item.id)
  if (ids.length === 0) return
  const action = command === 'active' ? '启动' : '暂停'
  try {
    await ElMessageBox.confirm(
      `确定要${action}选中的 ${ids.length} 个话题监控吗？`,
      `批量${action}确认`,
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  topicBatchStatusLoading.value = true
  try {
    const res: any = await batchUpdateTopicMonitorStatus(ids, command)
    if (res.code === 200) {
      ElMessage.success(res.message || `批量${action}成功`)
      selectedTopicMonitors.value = []
      fetchTopicMonitors()
    } else {
      ElMessage.error(res.message || `批量${action}失败`)
    }
  } finally {
    topicBatchStatusLoading.value = false
  }
}

function openTopicBatchIntervalDialog() {
  if (selectedTopicMonitors.value.length === 0) return
  const intervals = new Set(selectedTopicMonitors.value.map((item) => item.poll_interval_min))
  topicBatchPollInterval.value = intervals.size === 1
    ? selectedTopicMonitors.value[0].poll_interval_min
    : 5
  topicBatchIntervalDialogVisible.value = true
}

async function handleTopicBatchIntervalSubmit() {
  const ids = selectedTopicMonitors.value.map((item) => item.id)
  if (ids.length === 0) return
  topicBatchIntervalLoading.value = true
  try {
    const res: any = await batchUpdateTopicMonitorPollInterval(ids, topicBatchPollInterval.value)
    if (res.code === 200) {
      ElMessage.success(res.message || '批量设置成功')
      topicBatchIntervalDialogVisible.value = false
      selectedTopicMonitors.value = []
      fetchTopicMonitors()
    } else {
      ElMessage.error(res.message || '批量设置失败')
    }
  } finally {
    topicBatchIntervalLoading.value = false
  }
}

// ── Create Topic dialog ──
const topicCreateDialogVisible = ref(false)
const topicCreateFormRef = ref<FormInstance>()
const topicSubmitLoading = ref(false)

const topicCreateForm = reactive({ topic: '', industry: '', description: '', poll_interval_min: 5 })
const topicCreateRules: FormRules = {
  topic: [{ required: true, message: '请输入监控话题/行业', trigger: 'blur' }],
}

function openTopicCreateDialog() {
  topicCreateForm.topic = ''
  topicCreateForm.industry = ''
  topicCreateForm.description = ''
  topicCreateForm.poll_interval_min = 5
  topicCreateDialogVisible.value = true
}

async function handleTopicCreate() {
  if (!topicCreateFormRef.value) return
  const valid = await topicCreateFormRef.value.validate().catch(() => false)
  if (!valid) return
  topicSubmitLoading.value = true
  try {
    const res: any = await createTopicMonitor(topicCreateForm)
    if (res.code === 200) {
      ElMessage.success('话题监控创建成功')
      topicCreateDialogVisible.value = false
      fetchTopicMonitors()
    } else {
      ElMessage.error(res.message || '创建失败')
    }
  } finally {
    topicSubmitLoading.value = false
  }
}

// ── Edit Topic dialog ──
const topicEditDialogVisible = ref(false)
const topicEditFormRef = ref<FormInstance>()
const topicEditForm = reactive({ id: 0, topic: '', industry: '', description: '', poll_interval_min: 5 })

function openTopicEditDialog(row: TopicMonitorItem) {
  topicEditForm.id = row.id
  topicEditForm.topic = row.topic
  topicEditForm.industry = row.industry
  topicEditForm.description = row.description
  topicEditForm.poll_interval_min = row.poll_interval_min
  topicEditDialogVisible.value = true
}

async function handleTopicEdit() {
  topicSubmitLoading.value = true
  try {
    const res: any = await updateTopicMonitor(topicEditForm.id, {
      topic: topicEditForm.topic,
      industry: topicEditForm.industry,
      description: topicEditForm.description,
      poll_interval_min: topicEditForm.poll_interval_min,
    })
    if (res.code === 200) {
      ElMessage.success('更新成功')
      topicEditDialogVisible.value = false
      fetchTopicMonitors()
    } else {
      ElMessage.error(res.message || '更新失败')
    }
  } finally {
    topicSubmitLoading.value = false
  }
}

// ── Topic Toggle ──
async function handleTopicToggle(row: TopicMonitorItem & { _toggleLoading?: boolean }) {
  row._toggleLoading = true
  try {
    const res: any = await toggleTopicMonitor(row.id)
    if (res.code === 200) {
      ElMessage.success(res.data?.status === 'active' ? '已启动' : '已暂停')
      fetchTopicMonitors()
    } else {
      ElMessage.error(res.message || '操作失败')
      fetchTopicMonitors()
    }
  } catch {
    fetchTopicMonitors()
  } finally {
    row._toggleLoading = false
  }
}

// ── Topic Delete ──
async function handleTopicDelete(row: TopicMonitorItem) {
  try {
    await ElMessageBox.confirm(`确定要删除话题监控"${row.topic}"吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  topicSubmitLoading.value = true
  try {
    const res: any = await deleteTopicMonitor(row.id)
    if (res.code === 200) {
      ElMessage.success('删除成功')
      fetchTopicMonitors()
    } else {
      ElMessage.error(res.message || '删除失败')
    }
  } finally {
    topicSubmitLoading.value = false
  }
}

async function handleTopicBatchDelete() {
  const ids = selectedTopicMonitors.value.map((item) => item.id)
  if (ids.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${ids.length} 个话题监控吗？`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  topicBatchDeleteLoading.value = true
  try {
    const res: any = await batchDeleteTopicMonitors(ids)
    if (res.code === 200) {
      ElMessage.success(res.message || '批量删除成功')
      if (ids.length === topicMonitorList.value.length && topicPagination.page > 1) {
        topicPagination.page -= 1
      }
      selectedTopicMonitors.value = []
      fetchTopicMonitors()
    } else {
      ElMessage.error(res.message || '批量删除失败')
    }
  } finally {
    topicBatchDeleteLoading.value = false
  }
}

// ═══════════════════════════════════════════════════════════════
//  已移出账号
// ═══════════════════════════════════════════════════════════════

const removedList = ref<MonitorItem[]>([])
const removedTableLoading = ref(false)
const removedSearchText = ref('')
const removedPagination = reactive({ page: 1, pageSize: 20, total: 0 })
const selectedRemovedMonitors = ref<MonitorItem[]>([])
const removedBatchDeleteLoading = ref(false)

async function fetchRemovedMonitors() {
  removedTableLoading.value = true
  try {
    const res: any = await getRemovedMonitors({
      page: removedPagination.page,
      page_size: removedPagination.pageSize,
      search: removedSearchText.value || undefined,
    })
    if (res.code === 200) {
      removedList.value = res.data || []
      removedPagination.total = res.total
    }
  } finally {
    removedTableLoading.value = false
  }
}

function handleRemovedSearch() {
  removedPagination.page = 1
  fetchRemovedMonitors()
}

async function handleRemovedBatchDelete() {
  const ids = selectedRemovedMonitors.value.map((item) => item.id)
  if (ids.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${ids.length} 个已移出账号吗？删除后将无法在此处恢复。`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  removedBatchDeleteLoading.value = true
  try {
    const res: any = await batchDeleteMonitors(ids)
    if (res.code === 200) {
      ElMessage.success(res.message || '批量删除成功')
      if (ids.length === removedList.value.length && removedPagination.page > 1) {
        removedPagination.page -= 1
      }
      selectedRemovedMonitors.value = []
      fetchRemovedMonitors()
    } else {
      ElMessage.error(res.message || '批量删除失败')
    }
  } finally {
    removedBatchDeleteLoading.value = false
  }
}

async function handleRestore(row: MonitorItem) {
  try {
    await ElMessageBox.confirm(
      `确认恢复账号 "${row.nickname || row.douyin_uid}" 到监控池？`,
      '恢复确认',
      { type: 'info', confirmButtonText: '恢复', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const res: any = await restoreMonitor(row.id)
    if (res.code === 200) {
      ElMessage.success('账号已恢复')
      fetchRemovedMonitors()
    } else {
      ElMessage.error(res.message || '恢复失败')
    }
  } catch {
    ElMessage.error('恢复失败')
  }
}

// ── Init ──
onMounted(() => {
  fetchMonitors()
})
</script>

<style scoped lang="scss">
.page-container {
  padding: 0;
}

.page-header {
  margin-bottom: 16px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}

.flex-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.stats-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.stats-summary {
  margin-bottom: 20px;
}

.summary-item {
  padding: 16px;
  text-align: center;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}

.summary-label {
  color: #909399;
  font-size: 13px;
}

.summary-value {
  margin-top: 6px;
  color: #303133;
  font-size: 24px;
  font-weight: 600;
}

.stats-section-title {
  margin: 18px 0 10px;
  color: #303133;
}
</style>
