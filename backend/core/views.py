import base64
import binascii
import hashlib
import json
import os
import secrets
import traceback
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from django.conf import settings as django_settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.http.multipartparser import MultiPartParserError
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import AiUser, AppSetting, Conversation, Message, Recharge, SessionToken

try:
    from alipay import AliPay
except ImportError:
    AliPay = None

SESSION_DAYS = 7


def endpoint(view_func):
    @csrf_exempt
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except ApiError as error:
            return JsonResponse({"error": error.code, "message": error.message}, status=error.status)
        except Exception as error:
            traceback.print_exc()
            return JsonResponse({"error": "SERVER_ERROR", "message": "服务暂时不可用"}, status=500)

    return wrapper


@endpoint
def health(request):
    require_method(request, "GET")
    return JsonResponse({"status": "ok", "commit": os.environ.get("RENDER_GIT_COMMIT", "")[:7]})


@endpoint
def register(request):
    require_method(request, "POST")
    body = read_body(request)
    account = normalize_account(body.get("account"))
    password = str(body.get("password") or "")
    if not account or len(password) < 6:
        raise ApiError(400, "BAD_REQUEST", "请输入账号和至少 6 位密码")
    existing_user = AiUser.objects.filter(account=account).first()
    if existing_user:
        if existing_user.status == "pending":
            raise ApiError(409, "ACCOUNT_PENDING", "该账号已提交注册申请，请等待后台审核")
        raise ApiError(409, "ACCOUNT_EXISTS", "账号已存在，请直接登录")

    user = AiUser.objects.create(
        account=account,
        name=str(body.get("name") or account).strip()[:24],
        password_hash=hash_password(password),
        credits=0,
        status="pending",
    )
    return JsonResponse(
        {
            "user": public_user(user),
            "message": "注册申请已提交，请等待后台审核通过后再登录",
        },
        status=201,
    )


@endpoint
def login(request):
    require_method(request, "POST")
    body = read_body(request)
    account = normalize_account(body.get("account"))
    user = AiUser.objects.filter(account=account).first()
    if not user:
        raise ApiError(401, "INVALID_LOGIN", "账号密码不存在")
    if user.password_hash != hash_password(str(body.get("password") or "")):
        raise ApiError(401, "INVALID_LOGIN", "账号密码不存在")
    if user.status == "pending":
        raise ApiError(403, "ACCOUNT_PENDING", "账号正在审核中，请等待后台审核通过后再登录")
    if user.status != "active":
        raise ApiError(403, "ACCOUNT_DISABLED", "账号已被禁用，请联系管理员")

    token = create_session(user=user, role="user")
    return JsonResponse({"token": token, "user": public_user(user), "settings": public_settings(get_app_settings())})


@endpoint
def admin_login(request):
    require_method(request, "POST")
    body = read_body(request)
    if body.get("account") != django_settings.ADMIN_USER or body.get("password") != django_settings.ADMIN_PASSWORD:
        raise ApiError(401, "INVALID_LOGIN", "Invalid admin account or password")
    token = create_session(user=None, role="admin")
    return JsonResponse({"token": token, "admin": {"account": django_settings.ADMIN_USER}})


@endpoint
def me(request):
    require_method(request, "GET")
    user = require_user(request)
    return JsonResponse({"user": public_user(user), "settings": public_settings(get_app_settings())})


@endpoint
def conversations(request):
    require_method(request, "GET")
    user = require_user(request)
    items = []
    queryset = Conversation.objects.filter(user=user).prefetch_related("messages").order_by("-updated_at")
    for item in queryset:
        last_message = item.messages.order_by("-created_at").first()
        last_image = item.messages.filter(type="image").exclude(image_url="").order_by("-created_at").first()
        last_user_image = (
            item.messages.filter(role="user", type="image")
            .exclude(image_url="")
            .order_by("-created_at")
            .first()
        )
        items.append(
            {
                "id": item.id,
                "title": item.title,
                "mode": item.mode,
                "updatedAt": iso(item.updated_at),
                "lastMessage": last_message.content if last_message else "",
                "lastImageUrl": first_message_image_url(last_image),
                "referenceImageUrl": first_message_image_url(last_user_image),
            }
        )
    return JsonResponse({"conversations": items})


@endpoint
def conversation_detail(request, conversation_id):
    require_method(request, "GET")
    user = require_user(request)
    conversation = Conversation.objects.filter(id=conversation_id, user=user).first()
    if not conversation:
        raise ApiError(404, "NOT_FOUND", "Conversation does not exist")
    return JsonResponse(
        {
            "conversation": {
                "id": conversation.id,
                "title": conversation.title,
                "mode": conversation.mode,
                "createdAt": iso(conversation.created_at),
                "updatedAt": iso(conversation.updated_at),
                "messages": [public_message(message) for message in conversation.messages.order_by("created_at")],
            }
        }
    )


@endpoint
def chat(request):
    require_method(request, "POST")
    user = require_user(request)
    body, uploaded_images = read_chat_body(request)
    prompt = str(body.get("message") or "").strip()
    mode = resolve_request_mode(body.get("mode"))
    if not prompt:
        raise ApiError(400, "EMPTY_MESSAGE", "Please enter a message")

    app_settings = get_app_settings()
    ensure_ai_provider_configured(get_ai_api_base(app_settings), get_ai_api_key(app_settings))
    cost = app_settings.image_cost if mode == "image" else app_settings.chat_cost
    if user.credits < cost:
        raise ApiError(402, "NO_CREDITS", "Insufficient credits; please recharge first")

    conversation = None
    conversation_id = body.get("conversationId")
    if conversation_id:
        conversation = Conversation.objects.filter(id=conversation_id, user=user).first()
    if not conversation:
        conversation = Conversation.objects.create(user=user, title=prompt[:24], mode=mode)
    else:
        conversation.mode = mode
        conversation.save(update_fields=["mode", "updated_at"])

    reference_images = collect_image_references(conversation, uploaded_images)
    user_message = Message.objects.create(
        conversation=conversation,
        role="user",
        type="image" if uploaded_images else "text",
        content=prompt,
        image_url=serialize_image_urls([image["data_url"] for image in uploaded_images]),
    )
    ai_message = create_ai_message(conversation, mode, prompt, app_settings, reference_images)
    user.credits = money(user.credits - cost)
    user.save(update_fields=["credits"])

    return JsonResponse(
        {
            "conversationId": conversation.id,
            "messages": [public_message(user_message), public_message(ai_message)],
            "user": public_user(user),
        }
    )


@endpoint
def recharge(request):
    require_method(request, "POST")
    user = require_user(request)
    body = read_body(request)
    amount = parse_money(body.get("amount"))
    if amount <= 0:
        raise ApiError(400, "BAD_AMOUNT", "Please enter a valid recharge amount")
    method = "alipay" if body.get("method") == "alipay" else "wechat"
    if method == "alipay":
        return create_alipay_recharge(user, amount)

    item = Recharge.objects.create(
        user=user,
        amount=amount,
        method=method,
        note=str(body.get("note") or "")[:120],
    )
    app_settings = get_app_settings()
    payment = app_settings.alipay_text if method == "alipay" else app_settings.wechat_pay_text
    return JsonResponse({"recharge": public_recharge(item), "payment": payment}, status=201)


def create_alipay_recharge(user, amount):
    ensure_credits_capacity(amount)
    app_settings = get_app_settings()
    alipay_client = get_alipay_client()
    out_trade_no = build_out_trade_no(user)
    item = Recharge.objects.create(
        user=user,
        amount=amount,
        method="alipay",
        out_trade_no=out_trade_no,
        note="支付宝 H5 支付",
    )
    order_string = alipay_client.api_alipay_trade_wap_pay(
        out_trade_no=out_trade_no,
        total_amount=str(amount),
        subject=f"{app_settings.app_name}余额充值",
        return_url=django_settings.ALIPAY_RETURN_URL or None,
        notify_url=get_required_alipay_notify_url(),
    )
    payment_url = f"{django_settings.ALIPAY_GATEWAY}?{order_string}"
    return JsonResponse(
        {"recharge": public_recharge(item), "paymentUrl": payment_url},
        status=201,
    )


@csrf_exempt
def alipay_notify(request):
    if request.method != "POST":
        return HttpResponse("failure", status=405)
    data = request.POST.dict()
    signature = data.pop("sign", "")
    if not signature:
        return HttpResponse("failure")
    try:
        alipay_client = get_alipay_client()
        if not alipay_client.verify(data, signature):
            return HttpResponse("failure")
        if data.get("app_id") and data.get("app_id") != django_settings.ALIPAY_APP_ID:
            return HttpResponse("failure")
        out_trade_no = data.get("out_trade_no", "")
        trade_status = data.get("trade_status", "")
        total_amount = money(Decimal(str(data.get("total_amount") or "0")))
        with transaction.atomic():
            item = Recharge.objects.select_related("user").select_for_update().filter(
                out_trade_no=out_trade_no,
                method="alipay",
            ).first()
            if not item or total_amount != item.amount:
                return HttpResponse("failure")
            provider_trade_no = str(data.get("trade_no") or "")[:80]
            update_fields = ["provider_trade_no"]
            if trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"} and item.status != "confirmed":
                ensure_credits_capacity(item.amount)
                item.user.credits = money(item.user.credits + item.amount)
                item.user.save(update_fields=["credits"])
                item.status = "confirmed"
                item.handled_at = timezone.now()
                update_fields.extend(["status", "handled_at"])
            if provider_trade_no != item.provider_trade_no:
                item.provider_trade_no = provider_trade_no
            item.save(update_fields=update_fields)
    except (InvalidOperation, ValueError, ApiError):
        return HttpResponse("failure")
    except Exception:
        traceback.print_exc()
        return HttpResponse("failure")
    return HttpResponse("success")


@endpoint
def admin_overview(request):
    require_method(request, "GET")
    require_admin(request)
    app_settings = get_app_settings()
    total_credits = get_total_allocated_credits()
    pending_amount = (
        Recharge.objects.filter(status="pending").aggregate(total=Sum("amount")).get("total") or Decimal("0")
    )
    return JsonResponse(
        {
            "stats": {
                "users": AiUser.objects.count(),
                "pendingUsers": AiUser.objects.filter(status="pending").count(),
                "conversations": Conversation.objects.count(),
                "pendingRecharges": Recharge.objects.filter(status="pending").count(),
                "totalCredits": float(total_credits),
                "totalAvailableCredits": float(app_settings.total_available_credits),
                "remainingCredits": float(money(app_settings.total_available_credits - total_credits)),
                "pendingAmount": float(pending_amount),
            },
            "settings": admin_settings_payload(app_settings),
        }
    )


@endpoint
def admin_users(request):
    require_method(request, "GET")
    require_admin(request)
    items = []
    for user in AiUser.objects.order_by("-created_at"):
        item = public_user(user)
        item.update({"createdAt": iso(user.created_at), "conversations": Conversation.objects.filter(user=user).count()})
        items.append(item)
    return JsonResponse({"users": items})


@endpoint
def admin_user_credits(request):
    require_method(request, "POST")
    require_admin(request)
    body = read_body(request)
    with transaction.atomic():
        user = AiUser.objects.select_for_update().filter(id=body.get("userId")).first()
        if not user:
            raise ApiError(404, "NOT_FOUND", "User does not exist")
        amount = parse_money(body.get("amount"))
        ensure_credits_capacity(amount)
        user.credits = money(user.credits + amount)
        user.save(update_fields=["credits"])
    return JsonResponse({"user": public_user(user)})


@endpoint
def admin_user_status(request):
    require_method(request, "POST")
    require_admin(request)
    body = read_body(request)
    next_status = str(body.get("status") or "")
    if next_status not in {"pending", "active", "disabled"}:
        raise ApiError(400, "BAD_STATUS", "用户状态不正确")
    with transaction.atomic():
        user = AiUser.objects.select_for_update().filter(id=body.get("userId")).first()
        if not user:
            raise ApiError(404, "NOT_FOUND", "用户不存在")
        update_fields = ["status"]
        if user.status == "pending" and next_status == "active":
            app_settings = get_app_settings()
            ensure_credits_capacity(app_settings.welcome_credits, app_settings)
            user.credits = money(user.credits + app_settings.welcome_credits)
            update_fields.append("credits")
        user.status = next_status
        user.save(update_fields=update_fields)
    return JsonResponse({"user": public_user(user)})


@endpoint
def admin_recharges(request):
    require_method(request, "GET")
    require_admin(request)
    items = [public_recharge(item) for item in Recharge.objects.select_related("user").order_by("-created_at")]
    return JsonResponse({"recharges": items})


@endpoint
def admin_confirm_recharge(request):
    require_method(request, "POST")
    require_admin(request)
    body = read_body(request)
    item = Recharge.objects.select_related("user").filter(id=body.get("rechargeId")).first()
    if not item:
        raise ApiError(404, "NOT_FOUND", "Recharge request does not exist")
    if item.status != "confirmed":
        with transaction.atomic():
            item = Recharge.objects.select_related("user").select_for_update().get(id=item.id)
            if item.status != "confirmed":
                ensure_credits_capacity(item.amount)
                item.user.credits = money(item.user.credits + item.amount)
                item.user.save(update_fields=["credits"])
                item.status = "confirmed"
                item.handled_at = timezone.now()
                item.save(update_fields=["status", "handled_at"])
    return JsonResponse({"recharge": public_recharge(item)})


@endpoint
def admin_settings(request):
    require_admin(request)
    app_settings = get_app_settings()
    if request.method == "GET":
        return JsonResponse({"settings": admin_settings_payload(app_settings)})
    require_method(request, "POST")
    body = read_body(request)
    total_available_credits = parse_money(
        body.get("totalAvailableCredits"),
        app_settings.total_available_credits,
    )
    if total_available_credits < 0:
        raise ApiError(400, "BAD_AMOUNT", "Total available credits cannot be less than 0")
    allocated_credits = get_total_allocated_credits()
    if total_available_credits < allocated_credits:
        raise ApiError(400, "CREDITS_LIMIT_EXCEEDED", "Total available credits cannot be less than allocated credits")
    app_settings.app_name = str(body.get("appName") or app_settings.app_name)[:24]
    app_settings.total_available_credits = total_available_credits
    app_settings.welcome_credits = parse_money(body.get("welcomeCredits"), app_settings.welcome_credits)
    app_settings.chat_cost = parse_money(body.get("chatCost"), app_settings.chat_cost)
    app_settings.image_cost = parse_money(body.get("imageCost"), app_settings.image_cost)
    app_settings.ai_relay_base_url = str(body.get("aiRelayBaseUrl") or "").strip()[:500]
    app_settings.ai_root_api_key = str(body.get("aiRootApiKey") or "").strip()[:256]
    app_settings.chat_model = str(body.get("chatModel") or app_settings.chat_model).strip()[:80]
    app_settings.image_model = str(body.get("imageModel") or app_settings.image_model).strip()[:80]
    app_settings.wechat_pay_text = str(body.get("wechatPayText") or "")[:500]
    app_settings.alipay_text = str(body.get("alipayText") or "")[:500]
    app_settings.save()
    return JsonResponse({"settings": admin_settings_payload(app_settings)})


def build_out_trade_no(user):
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    return f"R{timestamp}{user.id}{secrets.token_hex(4).upper()}"


def get_alipay_client():
    if AliPay is None:
        raise ApiError(503, "ALIPAY_SDK_MISSING", "支付宝 SDK 未安装，请先安装后端依赖")
    app_id = django_settings.ALIPAY_APP_ID.strip()
    private_key = load_alipay_key(django_settings.ALIPAY_APP_PRIVATE_KEY)
    public_key = load_alipay_key(django_settings.ALIPAY_PUBLIC_KEY)
    missing = []
    if not app_id:
        missing.append("ALIPAY_APP_ID")
    if not private_key:
        missing.append("ALIPAY_APP_PRIVATE_KEY")
    if not public_key:
        missing.append("ALIPAY_PUBLIC_KEY")
    if not get_required_alipay_notify_url(raise_error=False):
        missing.append("ALIPAY_NOTIFY_URL or SITE_BASE_URL")
    if missing:
        raise ApiError(503, "ALIPAY_NOT_CONFIGURED", f"支付宝支付未配置：{', '.join(missing)}")
    return AliPay(
        appid=app_id,
        app_notify_url=get_required_alipay_notify_url(),
        app_private_key_string=private_key,
        alipay_public_key_string=public_key,
        sign_type="RSA2",
        debug=django_settings.ALIPAY_DEBUG,
    )


def get_required_alipay_notify_url(raise_error=True):
    notify_url = (django_settings.ALIPAY_NOTIFY_URL or "").strip()
    if notify_url or not raise_error:
        return notify_url
    raise ApiError(503, "ALIPAY_NOT_CONFIGURED", "支付宝异步通知地址未配置")


def load_alipay_key(value):
    value = str(value or "").strip().replace("\\n", "\n")
    if not value:
        return ""
    if "\n" not in value:
        candidate = Path(value)
        if candidate.exists() and candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return value


def create_ai_message(conversation, mode, prompt, app_settings, reference_images=None):
    if mode == "image":
        image_prompt = build_image_prompt(conversation, prompt, reference_images or [])
        image_url = call_openai_compatible_image(image_prompt, app_settings, reference_images or [])
        return Message.objects.create(
            conversation=conversation,
            role="assistant",
            type="image",
            content="已根据你的要求生成图片",
            image_url=image_url,
        )
    reply = call_openai_compatible_chat(conversation, app_settings)
    return Message.objects.create(conversation=conversation, role="assistant", type="text", content=reply)


def resolve_request_mode(raw_mode):
    if os.environ.get("ALLOW_CHAT_MODE", "0") == "1" and raw_mode == "chat":
        return "chat"
    return "image"


def call_openai_compatible_chat(conversation, app_settings):
    api_key = get_ai_api_key(app_settings)
    api_base = get_ai_api_base(app_settings)
    ensure_ai_provider_configured(api_base, api_key)
    payload = {
        "model": get_chat_model(app_settings),
        "messages": build_chat_messages(conversation),
    }
    data = post_openai_compatible(api_base, "/v1/chat/completions", api_key, payload)
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ApiError(502, "AI_PROVIDER_BAD_RESPONSE", "AI provider returned an invalid chat response")


def call_openai_compatible_image(prompt, app_settings, reference_images=None):
    api_key = get_ai_api_key(app_settings)
    api_base = get_ai_api_base(app_settings)
    ensure_ai_provider_configured(api_base, api_key)
    inline_references = inline_images(reference_images or [])
    if inline_references:
        data = post_openai_compatible_multipart(
            api_base,
            "/v1/images/edits",
            api_key,
            {
                "model": app_settings.image_model or "gpt-image-1",
                "prompt": prompt,
                "size": "1024x1024",
            },
            build_image_file_items(inline_references),
        )
    else:
        payload = {
            "model": app_settings.image_model or "gpt-image-1",
            "prompt": prompt,
            "size": "1024x1024",
        }
        data = post_openai_compatible(api_base, "/v1/images/generations", api_key, payload)
    try:
        image = data["data"][0]
        if image.get("url"):
            return image["url"]
        if image.get("b64_json"):
            return "data:image/png;base64," + image["b64_json"]
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    raise ApiError(502, "AI_PROVIDER_BAD_RESPONSE", "AI provider returned an invalid image response")


def get_chat_model(app_settings):
    model = str(app_settings.chat_model or "").strip()
    if is_image_only_model(model):
        return os.environ.get("DEFAULT_CHAT_MODEL", "gpt-4o-mini")
    return model or os.environ.get("DEFAULT_CHAT_MODEL", "gpt-4o-mini")


def is_image_only_model(model):
    normalized = str(model or "").strip().lower()
    return normalized.startswith("gpt-image") or normalized in {"dall-e-2", "dall-e-3"}


def build_chat_messages(conversation):
    messages = [{"role": "system", "content": "You are a concise and reliable AI assistant. Continue from the conversation history when the user asks follow-up questions."}]
    for message in conversation.messages.order_by("created_at"):
        content = message.content.strip()
        if message.type == "image":
            if message.role == "user":
                content = f"{content}\n[The user provided a reference image for this request.]".strip()
            else:
                content = f"{content}\n[An image was generated and can be referenced by later follow-up requests.]".strip()
        if content:
            messages.append({"role": message.role, "content": content[:4000]})
    return [messages[0], *messages[1:][-16:]]


def build_image_prompt(conversation, prompt, reference_images):
    history = []
    previous_messages = conversation.messages.order_by("-created_at")[:8]
    for message in reversed(list(previous_messages)):
        if message.type == "image" and message.role == "assistant":
            history.append("上一轮生成了一张图片，后续要求应在这张图的基础上继续修改。")
        elif message.type == "image" and message.role == "user":
            history.append(f"用户上传了参考图，并说明：{message.content[:300]}")
        elif message.content:
            speaker = "用户" if message.role == "user" else "助手"
            history.append(f"{speaker}: {message.content[:300]}")
    reference_note = "本次有参考图片，请优先保持参考图的主体、构图和风格，只修改用户明确要求的部分。" if reference_images else ""
    context = "\n".join(history[-8:])
    return "\n".join(
        part
        for part in [
            "请作为连续图片编辑任务处理，不要把这次请求当成完全无上下文的新图。",
            reference_note,
            f"会话上下文:\n{context}" if context else "",
            f"本次要求: {prompt}",
        ]
        if part
    )


def collect_image_references(conversation, uploaded_images):
    references = []
    for uploaded_image in uploaded_images or []:
        references.append(uploaded_image["data_url"])
    previous_images = (
        Message.objects.filter(conversation=conversation, type="image")
        .exclude(image_url="")
        .order_by("-created_at")[:4]
    )
    for previous_image in previous_images:
        for image_url in message_image_urls(previous_image):
            if image_url not in references:
                references.append(image_url)
    return references[:8]


def read_chat_body(request):
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        try:
            post_data = request.POST
            uploaded_files = request.FILES
        except RequestDataTooBig:
            raise ApiError(413, "IMAGE_TOO_LARGE", "Image attachment must be smaller than 8 MB")
        except MultiPartParserError:
            raise ApiError(400, "BAD_IMAGE", "Invalid image upload")
        body = {
            "message": post_data.get("message", ""),
            "mode": post_data.get("mode", ""),
            "conversationId": post_data.get("conversationId", ""),
        }
        image_files = uploaded_files.getlist("images") or uploaded_files.getlist("image")
        return body, parse_uploaded_image_files(image_files)
    body = read_body(request)
    return body, parse_image_attachments(body)


def parse_uploaded_image_files(uploaded_files):
    return [parse_uploaded_image_file(uploaded_file) for uploaded_file in uploaded_files if uploaded_file]


def parse_uploaded_image_file(uploaded_file):
    if not uploaded_file:
        return None
    content_type = uploaded_file.content_type or ""
    if not content_type.startswith("image/"):
        raise ApiError(400, "BAD_IMAGE", "Please upload an image file")
    content = uploaded_file.read()
    if len(content) > 8 * 1024 * 1024:
        raise ApiError(413, "IMAGE_TOO_LARGE", "Image attachment must be smaller than 8 MB")
    encoded = base64.b64encode(content).decode("ascii")
    return {
        "data_url": f"data:{content_type};base64,{encoded}",
        "bytes": content,
        "mime": content_type,
        "filename": str(uploaded_file.name or "reference.png")[:80],
    }


def parse_image_attachment(value):
    if not value:
        return None
    if not isinstance(value, dict):
        raise ApiError(400, "BAD_IMAGE", "Invalid image attachment")
    data_url = str(value.get("dataUrl") or "")
    inline_image = parse_data_url_image(data_url, allow_empty=False)
    return {
        "data_url": data_url,
        "bytes": inline_image["bytes"],
        "mime": inline_image["mime"],
        "filename": str(value.get("name") or inline_image["filename"])[:80],
    }


def parse_image_attachments(body):
    values = body.get("imageAttachments")
    if values is None:
        values = [body.get("imageAttachment")] if body.get("imageAttachment") else []
    if not isinstance(values, list):
        raise ApiError(400, "BAD_IMAGE", "Invalid image attachment")
    return [image for image in (parse_image_attachment(value) for value in values) if image]


def inline_images(reference_images):
    images = []
    for image_url in reference_images:
        inline_image = parse_data_url_image(image_url, allow_empty=True)
        if inline_image:
            images.append(inline_image)
    return images


def build_image_file_items(inline_references):
    field = "image" if len(inline_references) == 1 else "image[]"
    return [
        {
            "field": field,
            "filename": inline_reference["filename"],
            "content_type": inline_reference["mime"],
            "content": inline_reference["bytes"],
        }
        for inline_reference in inline_references
    ]


def parse_data_url_image(data_url, allow_empty=False):
    if not data_url:
        return None if allow_empty else raise_bad_image()
    if not data_url.startswith("data:image/") or ";base64," not in data_url:
        return None if allow_empty else raise_bad_image()
    header, encoded = data_url.split(";base64,", 1)
    mime = header.removeprefix("data:")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None if allow_empty else raise_bad_image()
    if len(content) > 8 * 1024 * 1024:
        raise ApiError(413, "IMAGE_TOO_LARGE", "Image attachment must be smaller than 8 MB")
    extension = mime.split("/")[-1].split("+")[0] or "png"
    return {"bytes": content, "mime": mime, "filename": f"reference.{extension}"}


def raise_bad_image():
    raise ApiError(400, "BAD_IMAGE", "Please upload a valid base64 image")


def get_ai_api_base(app_settings):
    return (app_settings.ai_relay_base_url or os.environ.get("AI_API_BASE") or "").strip().rstrip("/")


def get_ai_api_key(app_settings):
    return (app_settings.ai_root_api_key or os.environ.get("AI_API_KEY") or "").strip()


def ensure_ai_provider_configured(api_base, api_key):
    if not api_base or not api_key:
        raise ApiError(503, "AI_PROVIDER_NOT_CONFIGURED", "系统维护，请联系管理员")


def post_openai_compatible(api_base, path, api_key, payload):
    try:
        url = build_openai_compatible_url(api_base, path)
    except ValueError as error:
        raise ApiError(502, "AI_PROVIDER_REQUEST_FAILED", f"AI provider request failed: {error}")
    body = json.dumps(payload).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as error:
        detail = format_ai_provider_error(error.read().decode("utf-8", errors="ignore"))
        raise ApiError(502, "AI_PROVIDER_REQUEST_FAILED", f"AI provider request failed: HTTP {error.code} {detail}".strip())
    except json.JSONDecodeError:
        raise ApiError(502, "AI_PROVIDER_REQUEST_FAILED", "AI provider returned invalid JSON")
    except (urllib_error.URLError, TimeoutError, ValueError, OSError) as error:
        raise ApiError(502, "AI_PROVIDER_REQUEST_FAILED", f"AI provider request failed: {format_network_error(error)}")


def post_openai_compatible_multipart(api_base, path, api_key, fields, file_items):
    try:
        url = build_openai_compatible_url(api_base, path)
    except ValueError as error:
        raise ApiError(502, "AI_PROVIDER_REQUEST_FAILED", f"AI provider multipart request failed: {error}")
    boundary = f"----ai-shell-{secrets.token_hex(12)}"
    chunks = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for file_item in file_items:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{file_item["field"]}"; '
                    f'filename="{file_item["filename"]}"\r\n'
                ).encode("utf-8"),
                f'Content-Type: {file_item["content_type"]}\r\n\r\n'.encode("utf-8"),
                file_item["content"],
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    request = urllib_request.Request(
        url,
        data=b"".join(chunks),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as error:
        detail = format_ai_provider_error(error.read().decode("utf-8", errors="ignore"))
        raise ApiError(502, "AI_PROVIDER_REQUEST_FAILED", f"AI provider multipart request failed: HTTP {error.code} {detail}".strip())
    except json.JSONDecodeError:
        raise ApiError(502, "AI_PROVIDER_REQUEST_FAILED", "AI provider returned invalid JSON")
    except (urllib_error.URLError, TimeoutError, ValueError, OSError) as error:
        raise ApiError(502, "AI_PROVIDER_REQUEST_FAILED", f"AI provider multipart request failed: {format_network_error(error)}")


def build_openai_compatible_url(api_base, path):
    api_base = normalize_ai_api_base(api_base)
    if api_base.endswith("/v1") and path.startswith("/v1/"):
        return f"{api_base}{path[3:]}"
    return f"{api_base}{path}"


def normalize_ai_api_base(api_base):
    api_base = str(api_base or "").strip().rstrip("/")
    if not api_base:
        raise ValueError("AI API base URL is empty")
    parsed = urllib_parse.urlparse(api_base)
    if not parsed.scheme:
        api_base = f"https://{api_base}"
        parsed = urllib_parse.urlparse(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("AI API base URL must be a valid http(s) URL")
    return api_base


def format_ai_provider_error(raw_body):
    body = (raw_body or "").strip()
    if not body:
        return ""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:300]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:300]
        if payload.get("message"):
            return str(payload["message"])[:300]
    return body[:300]


def format_network_error(error):
    reason = getattr(error, "reason", None)
    if reason:
        return str(reason)
    return str(error)


def require_user(request):
    session = require_session(request, "user")
    if not session.user or session.user.status != "active":
        raise ApiError(401, "UNAUTHORIZED", "Please log in first")
    return session.user


def require_admin(request):
    return require_session(request, "admin")


def require_session(request, role):
    token = bearer_token(request)
    session = SessionToken.objects.select_related("user").filter(token=token, role=role).first()
    if not session or session.expires_at < timezone.now():
        raise ApiError(401, "UNAUTHORIZED", "Login session has expired")
    return session


def create_session(user, role):
    token = secrets.token_hex(24)
    SessionToken.objects.create(
        token=token,
        user=user,
        role=role,
        expires_at=timezone.now() + timezone.timedelta(days=SESSION_DAYS),
    )
    SessionToken.objects.filter(expires_at__lt=timezone.now()).delete()
    return token


def get_app_settings():
    settings_obj, _ = AppSetting.objects.get_or_create(id=1)
    return settings_obj


def get_total_allocated_credits():
    return money(AiUser.objects.aggregate(total=Sum("credits")).get("total") or Decimal("0"))


def ensure_credits_capacity(delta, app_settings=None):
    delta = money(delta)
    if delta <= 0:
        return
    app_settings = app_settings or get_app_settings()
    allocated_credits = get_total_allocated_credits()
    if allocated_credits + delta > app_settings.total_available_credits:
        raise ApiError(400, "CREDITS_LIMIT_EXCEEDED", "Allocated credits cannot exceed total available credits")


def public_user(user):
    status_labels = {"pending": "待审核", "active": "正常", "disabled": "禁用"}
    return {
        "id": user.id,
        "account": user.account,
        "name": user.name,
        "credits": float(user.credits),
        "status": user.status,
        "statusLabel": status_labels.get(user.status, user.status),
    }


def public_settings(app_settings):
    return {
        "appName": app_settings.app_name,
        "chatCost": float(app_settings.chat_cost),
        "imageCost": float(app_settings.image_cost),
        "wechatPayText": app_settings.wechat_pay_text,
        "alipayText": app_settings.alipay_text,
    }


def serialize_image_urls(image_urls):
    image_urls = [image_url for image_url in image_urls if image_url]
    if not image_urls:
        return ""
    if len(image_urls) == 1:
        return image_urls[0]
    return json.dumps(image_urls, ensure_ascii=False)


def message_image_urls(message):
    if not message or not message.image_url:
        return []
    raw_value = message.image_url.strip()
    if raw_value.startswith("["):
        try:
            values = json.loads(raw_value)
        except json.JSONDecodeError:
            values = []
        if isinstance(values, list):
            return [str(value) for value in values if value]
    return [message.image_url]


def first_message_image_url(message):
    image_urls = message_image_urls(message)
    return image_urls[0] if image_urls else ""


def admin_settings_payload(app_settings):
    payload = public_settings(app_settings)
    allocated_credits = get_total_allocated_credits()
    payload["totalAvailableCredits"] = float(app_settings.total_available_credits)
    payload["allocatedCredits"] = float(allocated_credits)
    payload["remainingCredits"] = float(money(app_settings.total_available_credits - allocated_credits))
    payload["welcomeCredits"] = float(app_settings.welcome_credits)
    payload["aiRelayBaseUrl"] = app_settings.ai_relay_base_url
    payload["aiRootApiKey"] = app_settings.ai_root_api_key
    payload["chatModel"] = app_settings.chat_model
    payload["imageModel"] = app_settings.image_model
    return payload


def public_message(message):
    image_urls = message_image_urls(message)
    return {
        "id": message.id,
        "role": message.role,
        "type": message.type,
        "content": message.content,
        "imageUrl": image_urls[0] if image_urls else "",
        "imageUrls": image_urls,
        "createdAt": iso(message.created_at),
    }


def public_recharge(item):
    return {
        "id": item.id,
        "userId": item.user_id,
        "account": item.user.account,
        "amount": float(item.amount),
        "method": item.method,
        "status": item.status,
        "outTradeNo": item.out_trade_no,
        "providerTradeNo": item.provider_trade_no,
        "note": item.note,
        "createdAt": iso(item.created_at),
        "handledAt": iso(item.handled_at),
    }


def read_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        raise ApiError(400, "BAD_JSON", "Invalid request body")


def require_method(request, method):
    if request.method != method:
        raise ApiError(405, "METHOD_NOT_ALLOWED", "Request method is not supported")


def bearer_token(request):
    auth = request.headers.get("authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else ""


def normalize_account(account):
    return str(account or "").strip().lower()[:64]


def hash_password(password):
    return hashlib.sha256(f"ai-shell:{password}".encode("utf-8")).hexdigest()


def parse_money(value, fallback=None):
    try:
        return money(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        if fallback is not None:
            return fallback
        raise ApiError(400, "BAD_AMOUNT", "Please enter a valid amount")


def money(value):
    return Decimal(value).quantize(Decimal("0.01"))


def iso(value):
    return value.isoformat() if value else None


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)
