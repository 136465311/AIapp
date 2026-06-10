<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import {
  CheckCircle2,
  CircleDollarSign,
  CreditCard,
  Gauge,
  LogOut,
  RefreshCw,
  Save,
  Search,
  Settings,
  ShieldCheck,
  UserRoundCog,
  UsersRound,
  WalletCards
} from "lucide-vue-next";
import { api, formatDate, formatNumber, getToken, setToken } from "./api";

const token = ref(getToken());
const activeView = ref("overview");
const loading = ref(false);
const toast = ref("");
const search = ref("");
const stats = ref({
  users: 0,
  pendingUsers: 0,
  conversations: 0,
  pendingRecharges: 0,
  totalCredits: 0,
  totalAvailableCredits: 0,
  remainingCredits: 0,
  pendingAmount: 0
});
const users = ref([]);
const recharges = ref([]);
const settings = ref({
  appName: "AI 助手",
  totalAvailableCredits: 10000,
  allocatedCredits: 0,
  remainingCredits: 10000,
  welcomeCredits: 20,
  chatCost: 1,
  imageCost: 5,
  aiRelayBaseUrl: "",
  aiRootApiKey: "",
  chatModel: "gpt-4o-mini",
  imageModel: "gpt-image-1",
  wechatPayText: "",
  alipayText: ""
});

const loginForm = reactive({ account: "admin", password: "admin123" });
const creditForms = reactive({});
const settingsForm = reactive({
  appName: "",
  totalAvailableCredits: 0,
  welcomeCredits: 0,
  chatCost: 1,
  imageCost: 5,
  aiRelayBaseUrl: "",
  aiRootApiKey: "",
  chatModel: "gpt-4o-mini",
  imageModel: "gpt-image-1",
  wechatPayText: "",
  alipayText: ""
});

const navItems = [
  { key: "overview", label: "运营概览", icon: Gauge },
  { key: "users", label: "账号额度", icon: UsersRound },
  { key: "recharges", label: "充值确认", icon: CreditCard },
  { key: "settings", label: "系统设置", icon: Settings }
];

const filteredUsers = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  if (!keyword) return users.value;
  return users.value.filter((user) => `${user.account} ${user.name}`.toLowerCase().includes(keyword));
});

const pendingRecharges = computed(() => recharges.value.filter((item) => item.status === "pending"));
const creditUsagePercent = computed(() => {
  const total = Number(settings.value.totalAvailableCredits || 0);
  if (total <= 0) return 0;
  return Math.min(100, Math.round((Number(settings.value.allocatedCredits || 0) / total) * 100));
});

onMounted(async () => {
  if (!token.value) return;
  await loadAll().catch(() => {
    setToken("");
    token.value = "";
  });
});

async function submitLogin() {
  await run(async () => {
    const data = await api("/api/auth/admin-login", { method: "POST", body: loginForm });
    token.value = data.token;
    setToken(data.token);
    await loadAll();
    showToast("登录成功");
  });
}

async function loadAll() {
  await Promise.all([loadOverview(), loadUsers(), loadRecharges()]);
}

async function loadOverview() {
  const data = await api("/api/admin/overview", { token: token.value });
  stats.value = data.stats;
  applySettings(data.settings);
}

async function loadUsers() {
  const data = await api("/api/admin/users", { token: token.value });
  users.value = data.users;
  data.users.forEach((user) => {
    if (!creditForms[user.id]) creditForms[user.id] = { amount: "" };
  });
}

async function loadRecharges() {
  const data = await api("/api/admin/recharges", { token: token.value });
  recharges.value = data.recharges;
}

function applySettings(nextSettings) {
  settings.value = nextSettings;
  Object.assign(settingsForm, {
    appName: nextSettings.appName,
    totalAvailableCredits: nextSettings.totalAvailableCredits,
    welcomeCredits: nextSettings.welcomeCredits,
    chatCost: nextSettings.chatCost,
    imageCost: nextSettings.imageCost,
    aiRelayBaseUrl: nextSettings.aiRelayBaseUrl || "",
    aiRootApiKey: nextSettings.aiRootApiKey || "",
    chatModel: nextSettings.chatModel || "gpt-4o-mini",
    imageModel: nextSettings.imageModel || "gpt-image-1",
    wechatPayText: nextSettings.wechatPayText,
    alipayText: nextSettings.alipayText
  });
}

async function saveSettings() {
  await run(async () => {
    const data = await api("/api/admin/settings", {
      method: "POST",
      token: token.value,
      body: settingsForm
    });
    applySettings(data.settings);
    await loadOverview();
    showToast("系统设置已保存");
  });
}

async function assignCredits(user) {
  const amount = Number(creditForms[user.id]?.amount || 0);
  if (!amount) {
    showToast("请输入要分配的额度");
    return;
  }
  await run(async () => {
    await api("/api/admin/users/credits", {
      method: "POST",
      token: token.value,
      body: { userId: user.id, amount }
    });
    creditForms[user.id].amount = "";
    await Promise.all([loadOverview(), loadUsers()]);
    showToast("额度已分配");
  });
}

async function confirmRecharge(item) {
  await run(async () => {
    await api("/api/admin/recharges/confirm", {
      method: "POST",
      token: token.value,
      body: { rechargeId: item.id }
    });
    await Promise.all([loadOverview(), loadUsers(), loadRecharges()]);
    showToast("充值已确认");
  });
}

async function setUserStatus(user, status) {
  await run(async () => {
    await api("/api/admin/users/status", {
      method: "POST",
      token: token.value,
      body: { userId: user.id, status }
    });
    await Promise.all([loadOverview(), loadUsers()]);
    showToast(status === "disabled" ? "账号已禁用" : status === "active" ? "账号审核已通过" : "账号已设为待审核");
  });
}

function userStatusText(status) {
  return { pending: "待审核", active: "正常", disabled: "禁用" }[status] || status;
}

function toggleStatusText(status) {
  if (status === "pending") return "审核通过";
  return status === "active" ? "禁用" : "启用";
}

function nextStatus(status) {
  return status === "active" ? "disabled" : "active";
}

function logout() {
  setToken("");
  token.value = "";
}

async function run(task) {
  try {
    loading.value = true;
    await task();
  } catch (error) {
    showToast(error.message);
  } finally {
    loading.value = false;
  }
}

function showToast(message) {
  toast.value = message;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.value = "";
  }, 2400);
}
</script>

<template>
  <main class="admin-shell">
    <section v-if="!token" class="login-screen">
      <form class="login-panel" @submit.prevent="submitLogin">
        <div class="brand-row">
          <span class="brand-icon"><ShieldCheck :size="28" /></span>
          <div>
            <h1>AI 助手后台管理</h1>
            <p>管理账号、额度和系统配置</p>
          </div>
        </div>
        <label>
          <span>管理员账号</span>
          <input v-model.trim="loginForm.account" autocomplete="username" required />
        </label>
        <label>
          <span>管理员密码</span>
          <input v-model="loginForm.password" type="password" autocomplete="current-password" required />
        </label>
        <button class="primary-btn" :disabled="loading">
          <ShieldCheck :size="18" />
          登录后台
        </button>
      </form>
    </section>

    <section v-else class="workspace">
      <aside class="sidebar">
        <div class="product-mark">
          <span><ShieldCheck :size="24" /></span>
          <strong>后台管理</strong>
        </div>
        <button
          v-for="item in navItems"
          :key="item.key"
          :class="{ active: activeView === item.key }"
          @click="activeView = item.key"
        >
          <component :is="item.icon" :size="18" />
          {{ item.label }}
        </button>
        <button class="logout-btn" @click="logout">
          <LogOut :size="18" />
          退出登录
        </button>
      </aside>

      <section class="content">
        <header class="topbar">
          <div>
            <h1>{{ navItems.find((item) => item.key === activeView)?.label }}</h1>
            <p>当前总额度 {{ formatNumber(settings.totalAvailableCredits) }}，剩余额度 {{ formatNumber(settings.remainingCredits) }}</p>
          </div>
          <button class="icon-text-btn" :disabled="loading" @click="loadAll">
            <RefreshCw :size="17" />
            刷新
          </button>
        </header>

        <section v-show="activeView === 'overview'" class="view">
          <div class="metric-grid">
            <article class="metric">
              <span><WalletCards :size="20" /></span>
              <small>总可用额度</small>
              <strong>{{ formatNumber(settings.totalAvailableCredits) }}</strong>
            </article>
            <article class="metric">
              <span><CircleDollarSign :size="20" /></span>
              <small>已分配额度</small>
              <strong>{{ formatNumber(settings.allocatedCredits) }}</strong>
            </article>
            <article class="metric">
              <span><Gauge :size="20" /></span>
              <small>剩余额度</small>
              <strong>{{ formatNumber(settings.remainingCredits) }}</strong>
            </article>
            <article class="metric">
              <span><UsersRound :size="20" /></span>
              <small>账号数量</small>
              <strong>{{ stats.users }}</strong>
            </article>
            <article class="metric">
              <span><UserRoundCog :size="20" /></span>
              <small>待审核账号</small>
              <strong>{{ stats.pendingUsers }}</strong>
            </article>
          </div>

          <div class="usage-panel">
            <div class="usage-head">
              <strong>额度使用情况</strong>
              <span>{{ creditUsagePercent }}%</span>
            </div>
            <div class="progress-track">
              <div class="progress-fill" :style="{ width: `${creditUsagePercent}%` }"></div>
            </div>
          </div>
        </section>

        <section v-show="activeView === 'users'" class="view">
          <div class="toolbar">
            <label class="search-box">
              <Search :size="18" />
              <input v-model="search" placeholder="搜索账号或昵称" />
            </label>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>账号</th>
                  <th>昵称</th>
                  <th>余额</th>
                  <th>状态</th>
                  <th>分配额度</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in filteredUsers" :key="user.id">
                  <td>{{ user.account }}</td>
                  <td>{{ user.name }}</td>
                  <td>{{ formatNumber(user.credits) }}</td>
                  <td>
                    <span class="status-pill" :class="user.status">{{ userStatusText(user.status) }}</span>
                  </td>
                  <td>
                    <input
                      v-model.number="creditForms[user.id].amount"
                      class="amount-input"
                      type="number"
                      min="0"
                      step="0.01"
                      :max="settings.remainingCredits"
                      placeholder="输入额度"
                    />
                  </td>
                  <td class="actions">
                    <button class="small-action" :disabled="loading" @click="assignCredits(user)">
                      <CircleDollarSign :size="16" />
                      分配
                    </button>
                    <button
                      class="small-action muted"
                      :disabled="loading"
                      @click="setUserStatus(user, nextStatus(user.status))"
                    >
                      <UserRoundCog :size="16" />
                      {{ toggleStatusText(user.status) }}
                    </button>
                  </td>
                </tr>
                <tr v-if="filteredUsers.length === 0">
                  <td colspan="6" class="empty-cell">暂无账号</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-show="activeView === 'recharges'" class="view">
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>账号</th>
                  <th>金额</th>
                  <th>方式</th>
                  <th>状态</th>
                  <th>申请时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in recharges" :key="item.id">
                  <td>{{ item.account }}</td>
                  <td>{{ formatNumber(item.amount) }}</td>
                  <td>{{ item.method === "alipay" ? "支付宝" : "微信" }}</td>
                  <td>
                    <span class="status-pill" :class="item.status">{{ item.status === "confirmed" ? "已确认" : "待确认" }}</span>
                  </td>
                  <td>{{ formatDate(item.createdAt) }}</td>
                  <td>
                    <button v-if="item.status === 'pending'" class="small-action" :disabled="loading" @click="confirmRecharge(item)">
                      <CheckCircle2 :size="16" />
                      确认
                    </button>
                    <span v-else class="muted-text">{{ formatDate(item.handledAt) }}</span>
                  </td>
                </tr>
                <tr v-if="recharges.length === 0">
                  <td colspan="6" class="empty-cell">暂无充值申请</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="hint-line">待确认 {{ pendingRecharges.length }} 笔，确认时同样会校验总可用额度。</p>
        </section>

        <section v-show="activeView === 'settings'" class="view settings-layout">
          <form class="settings-form" @submit.prevent="saveSettings">
            <div class="form-section">
              <h2>额度控制</h2>
              <label>
                <span>总可用额度</span>
                <input v-model.number="settingsForm.totalAvailableCredits" type="number" min="0" step="0.01" required />
              </label>
              <div class="limit-summary">
                <span>已分配 {{ formatNumber(settings.allocatedCredits) }}</span>
                <span>剩余 {{ formatNumber(settings.remainingCredits) }}</span>
              </div>
            </div>

            <div class="form-section">
              <h2>基础设置</h2>
              <label>
                <span>应用名称</span>
                <input v-model.trim="settingsForm.appName" maxlength="24" required />
              </label>
              <label>
                <span>注册赠送额度</span>
                <input v-model.number="settingsForm.welcomeCredits" type="number" min="0" step="0.01" required />
              </label>
              <label>
                <span>聊天单次消耗</span>
                <input v-model.number="settingsForm.chatCost" type="number" min="0" step="0.01" required />
              </label>
              <label>
                <span>生图单次消耗</span>
                <input v-model.number="settingsForm.imageCost" type="number" min="0" step="0.01" required />
              </label>
            </div>

            <div class="form-section">
              <h2>AI 接入配置</h2>
              <label>
                <span>中转站地址</span>
                <input
                  v-model.trim="settingsForm.aiRelayBaseUrl"
                  type="url"
                  maxlength="500"
                  placeholder="https://api.example.com"
                />
              </label>
              <label>
                <span>根源 API Key</span>
                <input
                  v-model.trim="settingsForm.aiRootApiKey"
                  type="password"
                  maxlength="256"
                  autocomplete="new-password"
                  placeholder="sk-..."
                />
              </label>
              <div class="model-grid">
                <label>
                  <span>对话模型</span>
                  <input v-model.trim="settingsForm.chatModel" maxlength="80" placeholder="gpt-4o-mini" />
                </label>
                <label>
                  <span>生图模型</span>
                  <input v-model.trim="settingsForm.imageModel" maxlength="80" placeholder="gpt-image-1" />
                </label>
              </div>
              <p class="hint-line">用户端只请求本站后端，实际 AI 地址和 Key 由这里统一控制。</p>
            </div>

            <div class="form-section">
              <h2>收款说明</h2>
              <label>
                <span>微信收款说明</span>
                <textarea v-model="settingsForm.wechatPayText" rows="4" maxlength="500"></textarea>
              </label>
              <label>
                <span>支付宝收款说明</span>
                <textarea v-model="settingsForm.alipayText" rows="4" maxlength="500"></textarea>
              </label>
            </div>

            <button class="primary-btn save-btn" :disabled="loading">
              <Save :size="18" />
              保存系统设置
            </button>
          </form>
        </section>
      </section>
    </section>

    <div v-if="toast" class="toast">{{ toast }}</div>
  </main>
</template>

<style>
:root {
  color: #18202d;
  background: #f5f6f8;
  font-family:
    Inter, "Microsoft YaHei", "PingFang SC", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

button,
input,
textarea {
  font: inherit;
}

button {
  cursor: pointer;
}

.admin-shell {
  min-height: 100vh;
  background: #f5f6f8;
}

.login-screen {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: #eef2f6;
}

.login-panel {
  width: min(420px, 100%);
  display: grid;
  gap: 18px;
  padding: 32px;
  border: 1px solid #dce2ea;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 16px 40px rgba(31, 42, 55, 0.12);
}

.brand-row,
.product-mark {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-icon,
.product-mark span,
.metric span {
  display: inline-grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  color: #ffffff;
  background: #255f85;
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  font-size: 24px;
  line-height: 1.2;
}

h2 {
  font-size: 17px;
}

p,
small,
.hint-line,
.muted-text {
  color: #637083;
}

label {
  display: grid;
  gap: 8px;
  color: #374151;
  font-size: 14px;
}

input,
textarea {
  width: 100%;
  border: 1px solid #ccd5df;
  border-radius: 6px;
  padding: 11px 12px;
  color: #111827;
  background: #ffffff;
  outline: none;
}

textarea {
  resize: vertical;
}

input:focus,
textarea:focus {
  border-color: #2f6f96;
  box-shadow: 0 0 0 3px rgba(47, 111, 150, 0.14);
}

.primary-btn,
.icon-text-btn,
.small-action,
.sidebar button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  border-radius: 6px;
  min-height: 40px;
}

.primary-btn {
  padding: 11px 16px;
  color: #ffffff;
  background: #2f6f96;
  font-weight: 700;
}

.primary-btn:disabled,
.icon-text-btn:disabled,
.small-action:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.workspace {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  min-height: 100vh;
}

.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 20px 14px;
  border-right: 1px solid #dbe2ea;
  background: #ffffff;
}

.product-mark {
  padding: 8px 8px 20px;
  font-size: 18px;
}

.sidebar button {
  justify-content: flex-start;
  padding: 11px 12px;
  color: #475569;
  background: transparent;
}

.sidebar button.active {
  color: #163d59;
  background: #e7f1f7;
  font-weight: 700;
}

.logout-btn {
  margin-top: auto;
}

.content {
  min-width: 0;
  padding: 24px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.icon-text-btn {
  padding: 10px 14px;
  border: 1px solid #cfd8e3;
  color: #263445;
  background: #ffffff;
}

.view {
  display: grid;
  gap: 18px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.metric,
.usage-panel,
.table-wrap,
.settings-form {
  border: 1px solid #dce2ea;
  border-radius: 8px;
  background: #ffffff;
}

.metric {
  display: grid;
  gap: 10px;
  min-height: 142px;
  padding: 18px;
}

.metric strong {
  font-size: 26px;
}

.usage-panel {
  padding: 18px;
}

.usage-head,
.limit-summary,
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.progress-track {
  height: 12px;
  margin-top: 14px;
  overflow: hidden;
  border-radius: 999px;
  background: #e4e9ef;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: #2f6f96;
  transition: width 180ms ease;
}

.search-box {
  position: relative;
  width: min(360px, 100%);
}

.search-box svg {
  position: absolute;
  left: 12px;
  top: 50%;
  color: #718096;
  transform: translateY(-50%);
}

.search-box input {
  padding-left: 40px;
}

.table-wrap {
  overflow: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  min-width: 820px;
}

th,
td {
  padding: 14px 16px;
  border-bottom: 1px solid #e4e9ef;
  text-align: left;
  white-space: nowrap;
}

th {
  color: #5b6676;
  font-size: 13px;
  font-weight: 700;
  background: #f8fafc;
}

tr:last-child td {
  border-bottom: 0;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 13px;
  color: #155e3b;
  background: #ddf7e8;
}

.status-pill.disabled {
  color: #87520f;
  background: #fff1d6;
}

.status-pill.pending {
  color: #1b4f72;
  background: #e3f2fd;
}

.status-pill.confirmed {
  color: #155e3b;
  background: #ddf7e8;
}

.amount-input {
  width: 150px;
}

.actions {
  display: flex;
  gap: 8px;
}

.small-action {
  min-height: 34px;
  padding: 7px 10px;
  color: #ffffff;
  background: #2f6f96;
}

.small-action.muted {
  color: #2d3748;
  background: #e8edf2;
}

.empty-cell {
  padding: 28px 16px;
  color: #718096;
  text-align: center;
}

.hint-line {
  font-size: 14px;
}

.settings-layout {
  align-items: start;
}

.settings-form {
  display: grid;
  gap: 20px;
  max-width: 780px;
  padding: 22px;
}

.form-section {
  display: grid;
  gap: 14px;
  padding-bottom: 18px;
  border-bottom: 1px solid #e4e9ef;
}

.model-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.form-section:last-of-type {
  border-bottom: 0;
}

.limit-summary {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.limit-summary span {
  padding: 8px 10px;
  border-radius: 6px;
  color: #263445;
  background: #edf3f7;
}

.save-btn {
  justify-self: start;
}

.toast {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 20;
  max-width: min(420px, calc(100vw - 32px));
  padding: 12px 16px;
  border-radius: 7px;
  color: #ffffff;
  background: #1f2937;
  box-shadow: 0 12px 30px rgba(31, 41, 55, 0.24);
}

@media (max-width: 920px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: static;
    height: auto;
    flex-direction: row;
    flex-wrap: wrap;
    border-right: 0;
    border-bottom: 1px solid #dbe2ea;
  }

  .product-mark {
    width: 100%;
    padding-bottom: 10px;
  }

  .logout-btn {
    margin-top: 0;
  }

  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .content {
    padding: 16px;
  }

  .topbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }

  .model-grid {
    grid-template-columns: 1fr;
  }

  .sidebar button {
    flex: 1 1 136px;
  }

  .login-panel {
    padding: 24px;
  }
}
</style>
