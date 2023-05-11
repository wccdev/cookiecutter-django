from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UploadedFile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filename", models.CharField(max_length=255, verbose_name="文件名")),
                ("file", models.FileField(max_length=1024, upload_to="upload/%Y/%m/%d", verbose_name="文件")),
                ("remark", models.TextField(blank=True, max_length=255, verbose_name="备注")),
                ("upload_time", models.DateTimeField(auto_now_add=True, verbose_name="上传时间")),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="上传用户",
                    ),
                ),
            ],
            options={
                "verbose_name": "上传文件",
                "verbose_name_plural": "上传文件",
                "db_table": 'base"."uploaded_file',
            },
        ),
    ]
