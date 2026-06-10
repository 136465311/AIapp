from django.db import models


class AiUser(models.Model):
    STATUS_CHOICES = [("pending", "待审核"), ("active", "正常"), ("disabled", "禁用")]

    account = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=24)
    password_hash = models.CharField(max_length=64)
    credits = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.account


class SessionToken(models.Model):
    ROLE_CHOICES = [("user", "用户"), ("admin", "管理员")]

    token = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(AiUser, null=True, blank=True, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()


class Conversation(models.Model):
    MODE_CHOICES = [("chat", "聊天"), ("image", "生图")]

    user = models.ForeignKey(AiUser, on_delete=models.CASCADE)
    title = models.CharField(max_length=64)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default="chat")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Message(models.Model):
    ROLE_CHOICES = [("user", "用户"), ("assistant", "助手")]
    TYPE_CHOICES = [("text", "文本"), ("image", "图片")]

    conversation = models.ForeignKey(Conversation, related_name="messages", on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default="text")
    content = models.TextField()
    image_url = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Recharge(models.Model):
    METHOD_CHOICES = [("wechat", "微信"), ("alipay", "支付宝")]
    STATUS_CHOICES = [("pending", "待确认"), ("confirmed", "已确认")]

    user = models.ForeignKey(AiUser, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=16, choices=METHOD_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    out_trade_no = models.CharField(max_length=64, unique=True, null=True, blank=True)
    provider_trade_no = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)


class AppSetting(models.Model):
    app_name = models.CharField(max_length=24, default="AI 助手")
    total_available_credits = models.DecimalField(max_digits=12, decimal_places=2, default=10000)
    welcome_credits = models.DecimalField(max_digits=12, decimal_places=2, default=20)
    chat_cost = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    image_cost = models.DecimalField(max_digits=12, decimal_places=2, default=5)
    ai_relay_base_url = models.URLField(max_length=500, blank=True, default="")
    ai_root_api_key = models.CharField(max_length=256, blank=True, default="")
    chat_model = models.CharField(max_length=80, default="gpt-4o-mini")
    image_model = models.CharField(max_length=80, default="gpt-image-1")
    wechat_pay_text = models.TextField(default="请替换为你的微信收款码或收款说明")
    alipay_text = models.TextField(default="请替换为你的支付宝收款码或收款说明")
    updated_at = models.DateTimeField(auto_now=True)
