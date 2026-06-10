# AI 助手框架

这是一个可先跑起来的三端框架：

- `backend`: Django API 服务，负责账号、登录、余额、充值申请、后台额度管理。
- `frontend-user`: Vue 3 用户端 H5，负责注册登录、聊天、生图、余额和充值申请。
- `frontend-admin`: Vue 3 后台管理端，负责账号管理、额度分配、充值确认和系统设置。

## 本地启动

启动后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver 127.0.0.1:8000
```

启动用户端：

```powershell
cd frontend-user
npm install
npm run dev
```

启动后台管理端：

```powershell
cd frontend-admin
npm install
npm run dev
```

后台管理端默认访问 `http://127.0.0.1:5174/`，默认代理到 `http://127.0.0.1:8000`。

如果后端临时跑在其他端口，可以这样指定：

```powershell
$env:VITE_API_TARGET="http://127.0.0.1:8001"
npm run dev
```

后台默认账号：`admin`

后台默认密码：`admin123`

## 支付宝 H5 支付配置

后端支持支付宝手机网站支付。上线前在后端运行环境配置：

```powershell
$env:SITE_BASE_URL="https://你的后端域名"
$env:FRONTEND_USER_URL="https://你的用户端域名"
$env:ALIPAY_APP_ID="支付宝应用 AppID"
$env:ALIPAY_APP_PRIVATE_KEY="C:\secure\alipay_app_private_key.pem"
$env:ALIPAY_PUBLIC_KEY="C:\secure\alipay_public_key.pem"
$env:ALIPAY_NOTIFY_URL="https://你的后端域名/api/pay/alipay/notify"
$env:ALIPAY_RETURN_URL="https://你的用户端域名"
```

沙箱调试时额外配置：

```powershell
$env:ALIPAY_DEBUG="1"
```

私钥和支付宝公钥可以填 PEM 文件路径，也可以直接填密钥内容。支付成功后支付宝会请求 `ALIPAY_NOTIFY_URL`，后端验签、校验金额和订单号后自动给用户加余额。
