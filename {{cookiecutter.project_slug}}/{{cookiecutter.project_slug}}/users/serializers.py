from django.contrib.auth import get_user_model, login
from rest_framework import serializers
from drfexts.choices import SimpleStatus
from drfexts.serializers.serializers import WCCModelSerializer
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "name", "url"]

        extra_kwargs = {
            "url": {"view_name": "api:user-detail", "lookup_field": "username"}
        }


class UserLoginSerializer(WCCModelSerializer):
    username = serializers.SlugRelatedField(
        slug_field=User.USERNAME_FIELD,  # noqa
        queryset=User.objects.all(),
        error_messages={"does_not_exist": "账号不存在！"},
        write_only=True,
        required=True,
    )
    password = serializers.CharField(
        max_length=128,
        required=True,
        write_only=True,
        label="密码",
        style={"input_type": "password", "placeholder": "Password"},
    )

    def validate(self, attrs):
        password = attrs["password"]
        user = attrs["username"]

        if not user.check_password(password):
            raise ValidationError(detail="密码错误！")
        if not user.is_active:
            raise ValidationError(detail="该账号尚未激活！")
        if user.status == SimpleStatus.INVALID:
            raise ValidationError(detail="该账号已被停用！")

        return attrs

    def save(self):
        user = self.validated_data["username"]
        request = self.context.get("request")
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return user

    class Meta:
        model = User
        fields = ["username", "password"]
