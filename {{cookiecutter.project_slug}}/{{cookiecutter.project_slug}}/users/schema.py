from drf_spectacular.extensions import OpenApiSerializerExtension
from drf_spectacular.utils import Direction
from drfexts.serializers.serializers import WCCModelSerializer


class DynamicFieldsModelSerializerExtension(OpenApiSerializerExtension):
    """
    A ModelSerializer that takes an additional `fields` argument that
        controls which fields should be displayed.
        Taken from (only added ref_name)
        https://www.django-rest-framework.org/api-guide/serializers/#dynamically-modifying-fields

    See issue: https://github.com/tfranzel/drf-spectacular/issues/375
    """
    target_class = WCCModelSerializer  # this can also be an import string
    match_subclasses = True
    priority = -1

    def map_serializer(self, auto_schema: "AutoSchema", direction: Direction):  # noqa: F821
        return auto_schema._map_serializer(self.target, direction, bypass_extensions=True)

    def get_name(self, auto_schema, direction):
        # FIXME API-DOC 报错
        return self.target.ref_name
