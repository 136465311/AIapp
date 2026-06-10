<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import {
  CircleUserRound,
  CreditCard,
  Download,
  History,
  Image as ImageIcon,
  ImagePlus,
  Loader2,
  LogOut,
  Maximize2,
  Menu,
  MessageCircle,
  Plus,
  Send,
  Settings,
  Sparkles,
  Upload,
  X
} from "lucide-vue-next";
import { api, formatDate, getToken, setToken } from "./api";

const token = ref(getToken());
const authMode = ref("login");
const activePanel = ref("chat");
const drawerOpen = ref(false);
const loading = ref(false);
const toast = ref("");
const authNotice = ref("");
const user = ref(null);
const settings = ref({ appName: "AI 助手", imageCost: 5 });
const messages = ref([]);
const conversations = ref([]);
const currentConversationId = ref("");
const messageInput = ref("");
const paymentText = ref("");
const historySearch = ref("");
const imageAttachments = ref([]);
const imagePreview = ref(null);
const fileInput = ref(null);
const messagesEl = ref(null);
const thinkingStep = ref("");

const loginForm = reactive({ account: "", password: "" });
const registerForm = reactive({ name: "", account: "", password: "" });
const rechargeForm = reactive({ amount: 10, method: "alipay" });
const typingTimers = new Map();

const panelTitle = computed(() => {
  const titles = {
    chat: settings.value.appName || "AI 助手",
    history: "生图记录",
    profile: "个人中心",
    recharge: "余额充值",
    settings: "设置"
  };
  return titles[activePanel.value] || "AI 助手";
});

const filteredConversations = computed(() => {
  const keyword = historySearch.value.trim().toLowerCase();
  if (!keyword) return conversations.value;
  return conversations.value.filter((item) =>
    `${item.title} ${item.lastMessage}`.toLowerCase().includes(keyword)
  );
});

const canSend = computed(() => messageInput.value.trim() && !loading.value);

onMounted(async () => {
  if (!token.value) return;
  await refreshMe().catch(() => {
    setToken("");
    token.value = "";
  });
});

onBeforeUnmount(() => {
  typingTimers.forEach((timer) => window.clearInterval(timer));
});

async function submitLogin() {
  await run(async () => {
    try {
      const data = await api("/api/auth/login", { method: "POST", body: loginForm });
      authNotice.value = "";
      enterApp(data);
    } catch (error) {
      if (error.code === "ACCOUNT_PENDING") {
        authNotice.value = "账号正在审核中，请等待后台审核通过后再登录。";
      }
      throw error;
    }
  });
}

async function submitRegister() {
  await run(async () => {
    const data = await api("/api/auth/register", { method: "POST", body: registerForm });
    authNotice.value = data.message || "注册申请已提交，请等待后台审核通过后再登录。";
    registerForm.password = "";
    loginForm.account = registerForm.account;
    loginForm.password = "";
    authMode.value = "login";
    showToast(authNotice.value);
  });
}

function switchAuthMode(mode) {
  authMode.value = mode;
  authNotice.value = "";
}

function enterApp(data) {
  token.value = data.token;
  setToken(data.token);
  user.value = data.user;
  settings.value = data.settings;
  activePanel.value = "chat";
  showToast("登录成功");
}

async function refreshMe() {
  const data = await api("/api/me", { token: token.value });
  user.value = data.user;
  settings.value = data.settings;
}

function openPanel(panel) {
  activePanel.value = panel;
  drawerOpen.value = false;
  if (panel === "history") loadConversations();
  if (panel === "profile" || panel === "recharge" || panel === "settings") refreshMe();
}

function startNewChat() {
  currentConversationId.value = "";
  messages.value = [];
  clearImageAttachments();
  activePanel.value = "chat";
  drawerOpen.value = false;
}

async function sendMessage(prompt = "") {
  const text = (prompt || messageInput.value).trim();
  if (!text || loading.value) return;

  const requestMode = "image";
  const attachments = [...imageAttachments.value];
  const localUserMessage = normalizeMessage({
    id: `local-user-${Date.now()}`,
    role: "user",
    type: attachments.length ? "image" : "text",
    content: text,
    imageUrl: attachments[0]?.dataUrl || "",
    imageUrls: attachments.map((attachment) => attachment.dataUrl)
  });
  const pendingMessage = normalizeMessage({
    id: `pending-${Date.now()}`,
    role: "assistant",
    type: requestMode === "image" ? "image" : "text",
    content: requestMode === "image" ? "正在参考图片和上下文生成画面..." : "正在理解上下文并组织回答...",
    pending: true
  });

  messages.value.push(localUserMessage, pendingMessage);
  messageInput.value = "";
  clearImageAttachments();
  startThinking(requestMode, Boolean(attachments.length));
  scrollToBottom();

  await run(async () => {
    const body = new FormData();
    body.append("message", text);
    body.append("mode", requestMode);
    if (currentConversationId.value) body.append("conversationId", currentConversationId.value);
    attachments.forEach((attachment) => {
      body.append("images", attachment.file, attachment.name);
    });

    const data = await api("/api/chat", {
      method: "POST",
      token: token.value,
      body
    });
    currentConversationId.value = data.conversationId;
    replacePendingMessages(localUserMessage.id, pendingMessage.id, data.messages);
    user.value = data.user;
    paymentText.value = "";
  });
}

function replacePendingMessages(localUserId, pendingId, serverMessages) {
  messages.value = messages.value.filter((message) => message.id !== localUserId && message.id !== pendingId);
  const normalized = serverMessages.map((message, index) =>
    normalizeMessage(message, index === serverMessages.length - 1 && message.role === "assistant")
  );
  messages.value.push(...normalized);
  const assistant = normalized.find((message) => message.role === "assistant" && message.type === "text");
  if (assistant) startTyping(assistant);
  scrollToBottom();
}

async function loadConversations() {
  await run(async () => {
    const data = await api("/api/conversations", { token: token.value });
    conversations.value = data.conversations;
  }, false);
}

async function openConversation(conversationId) {
  await run(async () => {
    const data = await api(`/api/conversations/${conversationId}`, { token: token.value });
    currentConversationId.value = data.conversation.id;
    messages.value = data.conversation.messages.map((message) => normalizeMessage(message));
    activePanel.value = "chat";
    scrollToBottom();
  }, false);
}

async function submitRecharge() {
  await run(async () => {
    const data = await api("/api/recharge", {
      method: "POST",
      token: token.value,
      body: rechargeForm
    });
    if (data.paymentUrl) {
      showToast("正在跳转支付宝收银台");
      window.location.href = data.paymentUrl;
      return;
    }
    paymentText.value = data.payment;
    showToast("充值申请已提交，后台确认后到账");
  });
}

function logout() {
  setToken("");
  token.value = "";
  user.value = null;
  messages.value = [];
  currentConversationId.value = "";
  clearImageAttachments();
}

function normalizeMessage(message, animate = false) {
  const imageUrls = Array.isArray(message.imageUrls)
    ? message.imageUrls.filter(Boolean)
    : message.imageUrl
      ? [message.imageUrl]
      : [];
  return {
    ...message,
    imageUrls,
    imageLoadCount: 0,
    imageLoaded: message.type !== "image",
    imageFailed: false,
    displayContent: animate && message.type === "text" ? "" : message.content,
    pending: Boolean(message.pending)
  };
}

function startTyping(message) {
  const characters = Array.from(message.content || "");
  let index = 0;
  window.clearInterval(typingTimers.get(message.id));
  const timer = window.setInterval(() => {
    index += characters[index]?.charCodeAt(0) > 255 ? 1 : 2;
    message.displayContent = characters.slice(0, index).join("");
    scrollToBottom();
    if (index >= characters.length) {
      window.clearInterval(timer);
      typingTimers.delete(message.id);
    }
  }, 28);
  typingTimers.set(message.id, timer);
}

function startThinking(requestMode, hasAttachment) {
  const steps = [
    hasAttachment ? "读取你上传的参考图" : "查找上一张可继续修改的图片",
    "理解本次修改要求",
    "保持主体和风格一致",
    "生成图片并等待预览加载"
  ];
  let index = 0;
  thinkingStep.value = steps[index];
  window.clearInterval(startThinking.timer);
  startThinking.timer = window.setInterval(() => {
    index = (index + 1) % steps.length;
    thinkingStep.value = steps[index];
  }, 1200);
}

function stopThinking() {
  window.clearInterval(startThinking.timer);
  thinkingStep.value = "";
}

function chooseImage() {
  fileInput.value?.click();
}

function handleImageSelect(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (!files.length) return;
  const invalidFile = files.find((file) => !file.type.startsWith("image/"));
  if (invalidFile) {
    showToast("请上传图片文件");
    return;
  }
  const oversizedFile = files.find((file) => file.size > 8 * 1024 * 1024);
  if (oversizedFile) {
    showToast("单张图片不能超过 8 MB");
    return;
  }
  Promise.all(files.map(readImageFile))
    .then((attachments) => {
      imageAttachments.value = [...imageAttachments.value, ...attachments];
    })
    .catch(() => showToast("图片读取失败，请重试"));
}

function readImageFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve({
        name: file.name,
        type: file.type,
        file,
        dataUrl: String(reader.result || "")
      });
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function clearImageAttachments() {
  imageAttachments.value = [];
}

function removeImageAttachment(index) {
  imageAttachments.value = imageAttachments.value.filter((_, itemIndex) => itemIndex !== index);
}

function markImageLoaded(message) {
  message.imageLoadCount = (message.imageLoadCount || 0) + 1;
  message.imageLoaded = message.imageLoadCount >= Math.max(message.imageUrls?.length || 1, 1);
}

function markImageFailed(message) {
  message.imageLoaded = true;
  message.imageFailed = true;
}

function openImagePreview(imageUrl) {
  imagePreview.value = {
    url: imageUrl,
    downloadName: `ai-image-${Date.now()}.png`
  };
}

function closeImagePreview() {
  imagePreview.value = null;
}

async function run(task, showLoading = true) {
  try {
    if (showLoading) loading.value = true;
    await task();
  } catch (error) {
    removePendingMessage();
    showToast(error.message);
  } finally {
    loading.value = false;
    stopThinking();
  }
}

function removePendingMessage() {
  messages.value = messages.value.filter((message) => !message.pending);
}

function showToast(message) {
  toast.value = message;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.value = "";
  }, 2200);
}

async function scrollToBottom() {
  await nextTick();
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
}
</script>

<template>
  <main class="mobile-shell">
    <section v-if="!token" class="auth-screen">
      <div class="brand-mark"><Sparkles :size="34" /></div>
      <h1>欢迎使用 AI 助手</h1>
      <p>专注图片生成与连续改图，登录后即可开始。</p>
      <p v-if="authNotice" class="auth-notice">{{ authNotice }}</p>

      <form v-if="authMode === 'login'" class="auth-card" @submit.prevent="submitLogin">
        <label><span>账号 / 手机号</span><input v-model.trim="loginForm.account" autocomplete="username" placeholder="请输入账号" required /></label>
        <label><span>密码</span><input v-model="loginForm.password" type="password" autocomplete="current-password" placeholder="请输入密码" required /></label>
        <button class="primary-btn" :disabled="loading">登录</button>
        <button class="ghost-btn" type="button" @click="switchAuthMode('register')">注册新账号</button>
      </form>

      <form v-else class="auth-card" @submit.prevent="submitRegister">
        <label><span>昵称</span><input v-model.trim="registerForm.name" placeholder="用于展示，可不填" /></label>
        <label><span>账号 / 手机号</span><input v-model.trim="registerForm.account" autocomplete="username" placeholder="请输入账号" required /></label>
        <label><span>密码</span><input v-model="registerForm.password" type="password" autocomplete="new-password" placeholder="至少 6 位" required /></label>
        <button class="primary-btn" :disabled="loading">提交注册申请</button>
        <button class="ghost-btn" type="button" @click="switchAuthMode('login')">已有账号，去登录</button>
      </form>
    </section>

    <section v-else class="app-screen">
      <aside class="drawer" :class="{ open: drawerOpen }">
        <div class="drawer-user">
          <div class="avatar">{{ user?.name?.slice(0, 1) || "U" }}</div>
          <div><strong>{{ user?.name }}</strong><small>{{ user?.account }}</small></div>
        </div>
        <button @click="startNewChat"><MessageCircle :size="18" /> 新建生图</button>
        <button @click="openPanel('history')"><History :size="18" /> 生图记录</button>
        <button @click="openPanel('profile')"><CircleUserRound :size="18" /> 个人中心</button>
        <button @click="openPanel('recharge')"><CreditCard :size="18" /> 余额充值</button>
        <button @click="openPanel('settings')"><Settings :size="18" /> 设置</button>
        <button class="danger" @click="logout"><LogOut :size="18" /> 退出登录</button>
      </aside>
      <button v-if="drawerOpen" class="drawer-mask" aria-label="关闭菜单" @click="drawerOpen = false"></button>

      <header class="mobile-topbar">
        <button class="icon-btn" aria-label="打开菜单" @click="drawerOpen = true"><Menu :size="22" /></button>
        <strong>{{ panelTitle }}</strong>
        <button class="icon-btn" aria-label="新建生图" @click="startNewChat"><Plus :size="22" /></button>
      </header>

      <section v-show="activePanel === 'chat'" class="page chat-page">
        <div v-if="messages.length === 0" class="empty-chat">
          <div class="brand-mark small"><Sparkles :size="24" /></div>
          <h2>想生成或修改什么图片？</h2>
          <button @click="sendMessage('生成一张日落海边的电影感照片')"><ImageIcon :size="16" /> 日落海边电影感照片</button>
          <button @click="sendMessage('把画面改成高级杂志封面风格')"><ImageIcon :size="16" /> 改成杂志封面风格</button>
          <button @click="sendMessage('生成一张适合电商首页的产品主图')"><ImageIcon :size="16" /> 电商产品主图</button>
        </div>

        <div ref="messagesEl" class="messages">
          <article v-for="message in messages" :key="message.id" class="message" :class="[message.role, { pending: message.pending }]">
            <div v-if="message.pending" class="thinking-line">
              <Loader2 :size="16" class="spin" />
              <span>{{ thinkingStep || message.content }}</span>
            </div>
            <template v-else>
              <p v-if="message.displayContent || message.content">{{ message.displayContent }}</p>
              <div v-if="message.type === 'image' && message.imageUrls.length" :class="message.imageUrls.length > 1 ? 'image-grid' : 'image-frame'">
                <div v-if="!message.imageLoaded" class="image-loader">
                  <Loader2 :size="24" class="spin" />
                  <span>图片加载中</span>
                </div>
                <button
                  v-for="imageUrl in message.imageUrls"
                  :key="imageUrl"
                  class="image-tile"
                  type="button"
                  :disabled="message.role !== 'assistant'"
                  @click="message.role === 'assistant' && openImagePreview(imageUrl)"
                >
                  <img
                    :src="imageUrl"
                    alt="AI 生成图预览"
                    :class="{ visible: message.imageLoaded && !message.imageFailed }"
                    @load="markImageLoaded(message)"
                    @error="markImageFailed(message)"
                  />
                  <span v-if="message.role === 'assistant'" class="image-action"><Maximize2 :size="15" /></span>
                </button>
                <div v-if="message.imageFailed" class="image-error">图片加载失败</div>
              </div>
            </template>
          </article>
        </div>

        <form class="composer" @submit.prevent="sendMessage()">
          <div v-if="imageAttachments.length" class="attachment-preview">
            <div class="attachment-grid">
              <div v-for="(attachment, index) in imageAttachments" :key="`${attachment.name}-${index}`" class="attachment-thumb">
                <img :src="attachment.dataUrl" alt="上传的参考图" />
                <button type="button" aria-label="移除参考图" @click="removeImageAttachment(index)"><X :size="14" /></button>
              </div>
            </div>
            <button type="button" aria-label="清空参考图" @click="clearImageAttachments"><X :size="16" /></button>
          </div>
          <div class="composer-row">
            <button class="tool-btn" type="button" aria-label="上传参考图" title="上传参考图" @click="chooseImage">
              <Upload :size="18" />
            </button>
            <input ref="fileInput" class="file-input" type="file" accept="image/*" multiple @change="handleImageSelect" />
            <input v-model="messageInput" placeholder="描述要生成或修改的图片..." autocomplete="off" />
            <button class="send-btn" :disabled="!canSend" aria-label="发送"><Send :size="18" /></button>
          </div>
          <div class="composer-hint">
            <ImagePlus :size="14" />
            <span>上传图片后会按参考图修改；不上传时会继续参考本对话上一张图。</span>
          </div>
        </form>
      </section>

      <section v-show="activePanel === 'history'" class="page">
        <div class="search-row"><input v-model="historySearch" placeholder="搜索生图记录" /></div>
        <div class="list">
          <button v-for="item in filteredConversations" :key="item.id" class="list-item" @click="openConversation(item.id)">
            <img
              v-if="item.referenceImageUrl || item.lastImageUrl"
              class="history-thumb"
              :src="item.referenceImageUrl || item.lastImageUrl"
              alt="生图记录缩略图"
            />
            <span><strong>{{ item.title }}</strong><small>{{ item.lastMessage }}</small></span>
            <em>{{ formatDate(item.updatedAt) }}</em>
          </button>
          <p v-if="filteredConversations.length === 0" class="empty-line">暂无生图记录</p>
        </div>
      </section>

      <section v-show="activePanel === 'profile'" class="page">
        <div class="profile-head">
          <div class="avatar large">{{ user?.name?.slice(0, 1) || "U" }}</div>
          <h2>{{ user?.name }}</h2>
          <p>{{ user?.account }}</p>
        </div>
        <div class="balance-card">
          <span>我的余额（积分）</span>
          <strong>{{ Number(user?.credits || 0).toFixed(2) }}</strong>
          <button class="primary-btn small-btn" @click="openPanel('recharge')">去充值</button>
        </div>
        <div class="list">
          <button class="list-item" @click="openPanel('history')">生图记录 <span>›</span></button>
          <button class="list-item" @click="openPanel('recharge')">余额充值 <span>›</span></button>
          <button class="list-item" @click="openPanel('settings')">设置 <span>›</span></button>
        </div>
      </section>

      <section v-show="activePanel === 'recharge'" class="page">
        <div class="balance-line"><span>当前余额（积分）</span><strong>{{ Number(user?.credits || 0).toFixed(2) }}</strong></div>
        <form class="recharge-form" @submit.prevent="submitRecharge">
          <div class="amount-grid">
            <button v-for="amount in [10, 50, 100, 200]" :key="amount" type="button" :class="{ active: rechargeForm.amount === amount }" @click="rechargeForm.amount = amount">{{ amount }} 元</button>
          </div>
          <label><span>自定义金额</span><input v-model.number="rechargeForm.amount" type="number" min="1" step="1" required /></label>
          <div class="pay-methods">
            <label><input v-model="rechargeForm.method" type="radio" value="wechat" /> 微信支付</label>
            <label><input v-model="rechargeForm.method" type="radio" value="alipay" /> 支付宝支付</label>
          </div>
          <button class="primary-btn" :disabled="loading">{{ rechargeForm.method === "alipay" ? "去支付宝付款" : "提交充值申请" }}</button>
        </form>
        <div v-if="paymentText" class="payment-box"><strong>支付信息</strong><p>{{ paymentText }}</p></div>
      </section>

      <section v-show="activePanel === 'settings'" class="page">
        <div class="list">
          <div class="list-item static">生图单次消耗 <span>{{ settings.imageCost }}</span></div>
          <div class="list-item static">余额查询 <span>个人中心查看</span></div>
        </div>
      </section>
    </section>

    <div v-if="imagePreview" class="image-preview-modal" @click.self="closeImagePreview">
      <div class="image-preview-toolbar">
        <a class="preview-icon-btn" :href="imagePreview.url" :download="imagePreview.downloadName" aria-label="下载图片" title="下载图片">
          <Download :size="20" />
        </a>
        <button class="preview-icon-btn" type="button" aria-label="关闭预览" title="关闭预览" @click="closeImagePreview">
          <X :size="20" />
        </button>
      </div>
      <img :src="imagePreview.url" alt="放大预览" />
    </div>

    <div v-if="toast" class="toast">{{ toast }}</div>
  </main>
</template>
