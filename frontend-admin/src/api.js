const TOKEN_KEY = "ai_shell_admin_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api(path, options = {}) {
  const headers = { "content-type": "application/json", ...(options.headers || {}) };
  if (options.token) headers.authorization = `Bearer ${options.token}`;
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(formatApiMessage(data.message));
    error.code = data.error || "";
    error.status = response.status;
    throw error;
  }
  return data;
}

function formatApiMessage(message) {
  if (message === "Insufficient credits; please recharge first") {
    return "余额不足 请充值";
  }
  return message || "请求失败";
}

export function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function formatNumber(value) {
  return Number(value || 0).toFixed(2);
}
