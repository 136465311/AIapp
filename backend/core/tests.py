import json
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from .models import AiUser, AppSetting, Conversation, Message, Recharge
from .views import hash_password


class HealthTests(TestCase):
    def test_health_endpoint_returns_ok(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


class AuthReviewFlowTests(TestCase):
    def setUp(self):
        AppSetting.objects.create(
            id=1,
            total_available_credits=Decimal("100.00"),
            welcome_credits=Decimal("20.00"),
        )
        self.client = Client()

    def post_json(self, path, body, **headers):
        return self.client.post(
            path,
            data=json.dumps(body),
            content_type="application/json",
            **headers,
        )

    def admin_headers(self):
        response = self.post_json("/api/auth/admin-login", {"account": "admin", "password": "admin123"})
        return {"HTTP_AUTHORIZATION": f"Bearer {response.json()['token']}"}

    def test_missing_account_login_shows_generic_message(self):
        response = self.post_json("/api/auth/login", {"account": "new@example.com", "password": "secret123"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "INVALID_LOGIN")
        self.assertEqual(response.json()["message"], "账号密码不存在")

    def test_registered_account_waits_for_admin_approval(self):
        register = self.post_json(
            "/api/auth/register",
            {"account": "wait@example.com", "name": "Wait", "password": "secret123"},
        )

        self.assertEqual(register.status_code, 201)
        self.assertNotIn("token", register.json())
        user = AiUser.objects.get(account="wait@example.com")
        self.assertEqual(user.status, "pending")
        self.assertEqual(user.credits, Decimal("0.00"))

        login = self.post_json("/api/auth/login", {"account": "wait@example.com", "password": "secret123"})
        self.assertEqual(login.status_code, 403)
        self.assertEqual(login.json()["error"], "ACCOUNT_PENDING")

    def test_admin_approval_enables_login_and_grants_welcome_credits(self):
        self.post_json(
            "/api/auth/register",
            {"account": "approved@example.com", "name": "Approved", "password": "secret123"},
        )
        user = AiUser.objects.get(account="approved@example.com")

        approve = self.post_json(
            "/api/admin/users/status",
            {"userId": user.id, "status": "active"},
            **self.admin_headers(),
        )
        self.assertEqual(approve.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.status, "active")
        self.assertEqual(user.credits, Decimal("20.00"))

        login = self.post_json("/api/auth/login", {"account": "approved@example.com", "password": "secret123"})
        self.assertEqual(login.status_code, 200)
        self.assertIn("token", login.json())


class AdminCreditsLimitTests(TestCase):
    def setUp(self):
        AppSetting.objects.create(
            id=1,
            total_available_credits=Decimal("100.00"),
            welcome_credits=Decimal("0.00"),
        )
        self.user = AiUser.objects.create(
            account="user@example.com",
            name="User",
            password_hash="x" * 64,
            credits=Decimal("80.00"),
            status="active",
        )
        self.client = Client()
        response = self.client.post(
            "/api/auth/admin-login",
            data=json.dumps({"account": "admin", "password": "admin123"}),
            content_type="application/json",
        )
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {response.json()['token']}"}

    def post_admin_json(self, path, body):
        return self.client.post(
            path,
            data=json.dumps(body),
            content_type="application/json",
            **self.auth_headers,
        )

    def test_admin_cannot_lower_total_below_allocated_credits(self):
        response = self.post_admin_json("/api/admin/settings", {"totalAvailableCredits": 70})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "CREDITS_LIMIT_EXCEEDED")

    def test_admin_credit_assignment_cannot_exceed_total_available_credits(self):
        response = self.post_admin_json(
            "/api/admin/users/credits",
            {"userId": self.user.id, "amount": 21},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "CREDITS_LIMIT_EXCEEDED")
        self.user.refresh_from_db()
        self.assertEqual(self.user.credits, Decimal("80.00"))

    def test_admin_credit_assignment_can_use_remaining_credits(self):
        response = self.post_admin_json(
            "/api/admin/users/credits",
            {"userId": self.user.id, "amount": 20},
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.credits, Decimal("100.00"))

    def test_confirm_recharge_cannot_exceed_total_available_credits(self):
        recharge = Recharge.objects.create(
            user=self.user,
            amount=Decimal("21.00"),
            method="wechat",
        )

        response = self.post_admin_json(
            "/api/admin/recharges/confirm",
            {"rechargeId": recharge.id},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "CREDITS_LIMIT_EXCEEDED")
        self.user.refresh_from_db()
        recharge.refresh_from_db()
        self.assertEqual(self.user.credits, Decimal("80.00"))
        self.assertEqual(recharge.status, "pending")


class AiProviderSettingsTests(TestCase):
    def setUp(self):
        AppSetting.objects.create(
            id=1,
            total_available_credits=Decimal("1000.00"),
            welcome_credits=Decimal("0.00"),
        )
        self.user = AiUser.objects.create(
            account="chat@example.com",
            name="Chat User",
            password_hash=hash_password("secret123"),
            credits=Decimal("20.00"),
            status="active",
        )
        self.client = Client()
        admin_login = self.client.post(
            "/api/auth/admin-login",
            data=json.dumps({"account": "admin", "password": "admin123"}),
            content_type="application/json",
        )
        self.admin_headers = {"HTTP_AUTHORIZATION": f"Bearer {admin_login.json()['token']}"}
        user_login = self.client.post(
            "/api/auth/login",
            data=json.dumps({"account": self.user.account, "password": "secret123"}),
            content_type="application/json",
        )
        self.user_headers = {"HTTP_AUTHORIZATION": f"Bearer {user_login.json()['token']}"}

    def test_admin_can_save_ai_provider_settings(self):
        response = self.client.post(
            "/api/admin/settings",
            data=json.dumps(
                {
                    "totalAvailableCredits": 1000,
                    "appName": "AI 助手",
                    "welcomeCredits": 0,
                    "chatCost": 1,
                    "imageCost": 5,
                    "aiRelayBaseUrl": "https://relay.example.com/openai",
                    "aiRootApiKey": "root-key",
                    "chatModel": "relay-chat",
                    "imageModel": "relay-image",
                }
            ),
            content_type="application/json",
            **self.admin_headers,
        )

        self.assertEqual(response.status_code, 200)
        settings = response.json()["settings"]
        self.assertEqual(settings["aiRelayBaseUrl"], "https://relay.example.com/openai")
        self.assertEqual(settings["aiRootApiKey"], "root-key")
        self.assertEqual(settings["chatModel"], "relay-chat")
        self.assertEqual(settings["imageModel"], "relay-image")

    def test_user_settings_do_not_expose_ai_provider_secret(self):
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "https://relay.example.com"
        app_settings.ai_root_api_key = "root-key"
        app_settings.save()

        response = self.client.get("/api/me", **self.user_headers)

        self.assertEqual(response.status_code, 200)
        public_settings = response.json()["settings"]
        self.assertNotIn("aiRelayBaseUrl", public_settings)
        self.assertNotIn("aiRootApiKey", public_settings)

    def test_chat_requires_backend_configured_ai_provider(self):
        response = self.client.post(
            "/api/chat",
            data=json.dumps({"message": "hello", "mode": "chat"}),
            content_type="application/json",
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "AI_PROVIDER_NOT_CONFIGURED")
        self.assertEqual(response.json()["message"], "系统维护，请联系管理员")
        self.user.refresh_from_db()
        self.assertEqual(self.user.credits, Decimal("20.00"))
        self.assertEqual(Conversation.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Message.objects.count(), 0)

    @patch("core.views.urllib_request.urlopen")
    def test_chat_uses_backend_configured_ai_provider(self, mocked_urlopen):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "configured reply"}}]}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "https://relay.example.com/openai"
        app_settings.ai_root_api_key = "root-key"
        app_settings.chat_model = "relay-chat"
        app_settings.save()

        response = self.client.post(
            "/api/chat",
            data=json.dumps({"message": "hello", "mode": "chat"}),
            content_type="application/json",
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["messages"][1]["content"], "configured reply")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://relay.example.com/openai/v1/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer root-key")
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], "relay-chat")

    @patch("core.views.urllib_request.urlopen")
    def test_chat_accepts_ai_provider_base_without_scheme(self, mocked_urlopen):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "configured reply"}}]}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "relay.example.com/openai"
        app_settings.ai_root_api_key = "root-key"
        app_settings.save()

        response = self.client.post(
            "/api/chat",
            data=json.dumps({"message": "hello", "mode": "chat"}),
            content_type="application/json",
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 200)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://relay.example.com/openai/v1/chat/completions")

    def test_chat_returns_provider_error_for_invalid_ai_provider_base(self):
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "ftp://relay.example.com/openai"
        app_settings.ai_root_api_key = "root-key"
        app_settings.save()

        response = self.client.post(
            "/api/chat",
            data=json.dumps({"message": "hello", "mode": "chat"}),
            content_type="application/json",
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "AI_PROVIDER_REQUEST_FAILED")

    @patch("core.views.urllib_request.urlopen")
    def test_chat_falls_back_when_chat_model_is_image_only(self, mocked_urlopen):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "text reply"}}]}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "https://relay.example.com/openai"
        app_settings.ai_root_api_key = "root-key"
        app_settings.chat_model = "gpt-image-2"
        app_settings.save()

        response = self.client.post(
            "/api/chat",
            data=json.dumps({"message": "hello", "mode": "chat"}),
            content_type="application/json",
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 200)
        request_body = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_body["model"], "gpt-4o-mini")

    @patch("core.views.urllib_request.urlopen")
    def test_chat_sends_conversation_history_to_provider(self, mocked_urlopen):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "warmer reply"}}]}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "https://relay.example.com/openai"
        app_settings.ai_root_api_key = "root-key"
        app_settings.save()
        conversation = Conversation.objects.create(user=self.user, title="Draft", mode="chat")
        Message.objects.create(conversation=conversation, role="user", type="text", content="Write a launch note")
        Message.objects.create(conversation=conversation, role="assistant", type="text", content="Initial launch note")

        response = self.client.post(
            "/api/chat",
            data=json.dumps({"message": "Make it warmer", "mode": "chat", "conversationId": conversation.id}),
            content_type="application/json",
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 200)
        request = mocked_urlopen.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        contents = [item["content"] for item in request_body["messages"]]
        self.assertIn("Write a launch note", contents)
        self.assertIn("Initial launch note", contents)
        self.assertIn("Make it warmer", contents)

    @patch("core.views.urllib_request.urlopen")
    def test_image_mode_uses_uploaded_image_as_edit_reference(self, mocked_urlopen):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"data": [{"b64_json": "ZWRpdGVk"}]}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "https://relay.example.com/openai"
        app_settings.ai_root_api_key = "root-key"
        app_settings.image_model = "relay-image"
        app_settings.save()
        image_data_url = "data:image/png;base64,aW1hZ2U="

        response = self.client.post(
            "/api/chat",
            data=json.dumps(
                {
                    "message": "把背景改成夜景",
                    "mode": "image",
                    "imageAttachment": {"name": "reference.png", "type": "image/png", "dataUrl": image_data_url},
                }
            ),
            content_type="application/json",
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 200)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://relay.example.com/openai/v1/images/edits")
        self.assertIn("multipart/form-data", request.headers["Content-type"])
        self.assertIn(b'name="image"; filename="reference.png"', request.data)
        self.assertIn("把背景改成夜景".encode("utf-8"), request.data)
        user_message = Message.objects.get(role="user", type="image")
        self.assertEqual(user_message.image_url, image_data_url)
        self.assertTrue(response.json()["messages"][1]["imageUrl"].startswith("data:image/png;base64,"))

    @patch("core.views.urllib_request.urlopen")
    def test_image_mode_saves_multipart_upload_in_conversation_history(self, mocked_urlopen):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"data": [{"b64_json": "ZWRpdGVk"}]}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "https://relay.example.com/openai"
        app_settings.ai_root_api_key = "root-key"
        app_settings.image_model = "relay-image"
        app_settings.save()
        upload = SimpleUploadedFile("reference.png", b"image-bytes", content_type="image/png")

        response = self.client.post(
            "/api/chat",
            data={"message": "把背景改成夜景", "mode": "image", "image": upload},
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 200)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://relay.example.com/openai/v1/images/edits")
        self.assertIn(b'name="image"; filename="reference.png"', request.data)
        user_message = response.json()["messages"][0]
        self.assertEqual(user_message["type"], "image")
        self.assertTrue(user_message["imageUrl"].startswith("data:image/png;base64,"))

        detail = self.client.get(
            f"/api/conversations/{response.json()['conversationId']}",
            **self.user_headers,
        )
        self.assertEqual(detail.status_code, 200)
        history_message = detail.json()["conversation"]["messages"][0]
        self.assertEqual(history_message["type"], "image")
        self.assertTrue(history_message["imageUrl"].startswith("data:image/png;base64,"))

    @patch("core.views.urllib_request.urlopen")
    def test_image_mode_accepts_multiple_reference_images(self, mocked_urlopen):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"data": [{"b64_json": "ZWRpdGVk"}]}).encode("utf-8")

        mocked_urlopen.return_value = FakeResponse()
        app_settings = AppSetting.objects.get(id=1)
        app_settings.ai_relay_base_url = "https://relay.example.com/openai"
        app_settings.ai_root_api_key = "root-key"
        app_settings.image_model = "relay-image"
        app_settings.save()

        response = self.client.post(
            "/api/chat",
            data=json.dumps(
                {
                    "message": "Blend these references",
                    "mode": "image",
                    "imageAttachments": [
                        {"name": "first.png", "type": "image/png", "dataUrl": "data:image/png;base64,Zmlyc3Q="},
                        {"name": "second.png", "type": "image/png", "dataUrl": "data:image/png;base64,c2Vjb25k"},
                    ],
                }
            ),
            content_type="application/json",
            **self.user_headers,
        )

        self.assertEqual(response.status_code, 200)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.data.count(b'name="image[]"'), 2)
        user_message = response.json()["messages"][0]
        self.assertEqual(len(user_message["imageUrls"]), 2)

        detail = self.client.get(
            f"/api/conversations/{response.json()['conversationId']}",
            **self.user_headers,
        )
        history_message = detail.json()["conversation"]["messages"][0]
        self.assertEqual(len(history_message["imageUrls"]), 2)
