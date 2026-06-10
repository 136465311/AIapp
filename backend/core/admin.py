from django.contrib import admin

from .models import AiUser, AppSetting, Conversation, Message, Recharge, SessionToken

admin.site.register(AiUser)
admin.site.register(SessionToken)
admin.site.register(Conversation)
admin.site.register(Message)
admin.site.register(Recharge)
admin.site.register(AppSetting)
