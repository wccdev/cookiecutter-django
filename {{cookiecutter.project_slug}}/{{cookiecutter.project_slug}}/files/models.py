from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class UploadedFile(models.Model):
    """上传文件"""

    filename = models.CharField("文件名", max_length=255)
    file = models.FileField("文件", max_length=1024, upload_to="upload/%Y/%m/%d")
    remark = models.TextField("备注", max_length=255, blank=True)

    upload_time = models.DateTimeField("上传时间", auto_now_add=True)
    uploaded_by = models.ForeignKey(User, verbose_name="上传用户", on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "上传文件"
        db_table = 'base"."uploaded_file'

    def __str__(self):
        return self.filename

    @property
    def url(self):
        return self.file.url

    @property
    def filesize(self):
        return self.file.size
