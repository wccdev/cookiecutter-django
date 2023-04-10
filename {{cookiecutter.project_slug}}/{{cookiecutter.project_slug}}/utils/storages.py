{% if cookiecutter.cloud_provider == 'AWS' -%}
from storages.backends.s3boto3 import S3Boto3Storage


class StaticRootS3Boto3Storage(S3Boto3Storage):
    location = "static"
    default_acl = "public-read"


class MediaRootS3Boto3Storage(S3Boto3Storage):
    location = "media"
    file_overwrite = False
{%- elif cookiecutter.cloud_provider == 'Aliyun' -%}
from datetime import datetime, timedelta

from django.utils.encoding import filepath_to_uri
from storages.backends.s3boto3 import S3Boto3Storage
from storages.utils import clean_name


class StaticRootAliyunOSSStorage(S3Boto3Storage):
    location = "static"
    default_acl = "public-read"


class MediaRootAliyunOSSStorage(S3Boto3Storage):
    location = "media"
    file_overwrite = False

    def get_upload_url(self, name, parameters=None, expire=300, http_method=None):
        # Preserve the trailing slash after normalizing the path.
        name = self._normalize_name(clean_name(name))
        if expire is None:
            expire = self.querystring_expire

        if self.custom_domain:
            url = f"{self.url_protocol}//{self.custom_domain}/{filepath_to_uri(name)}"

            if self.cloudfront_signer:
                expiration = datetime.utcnow() + timedelta(seconds=expire)

                return self.cloudfront_signer.generate_presigned_url(url, date_less_than=expiration)

            return url

        params = parameters.copy() if parameters else {}
        params["Bucket"] = self.bucket.name
        params["Key"] = name
        return self.bucket.meta.client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expire, HttpMethod=http_method
        )
{%- elif cookiecutter.cloud_provider == 'GCP' -%}
from storages.backends.gcloud import GoogleCloudStorage


class StaticRootGoogleCloudStorage(GoogleCloudStorage):
    location = "static"
    default_acl = "publicRead"


class MediaRootGoogleCloudStorage(GoogleCloudStorage):
    location = "media"
    file_overwrite = False
{%- elif cookiecutter.cloud_provider == 'Azure' -%}
from storages.backends.azure_storage import AzureStorage


class StaticRootAzureStorage(AzureStorage):
    location = "static"


class MediaRootAzureStorage(AzureStorage):
    location = "media"
    file_overwrite = False
{%- endif %}
