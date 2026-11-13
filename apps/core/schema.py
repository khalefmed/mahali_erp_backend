from drf_spectacular import openapi
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers


class FieldErrorSerializer(serializers.Serializer):
    field = serializers.CharField(allow_null=True)
    code = serializers.CharField()
    detail = serializers.CharField()


class ProblemSerializer(serializers.Serializer):
    """RFC 9457 problem details. Translate `code` in the UI, never `detail`."""

    type = serializers.CharField()
    title = serializers.CharField()
    status = serializers.IntegerField()
    code = serializers.CharField()
    detail = serializers.CharField()
    errors = FieldErrorSerializer(many=True, required=False)
    retry_after = serializers.IntegerField(required=False)


ERROR_STATUSES = {
    "400": "Validation error (`code` = validation_error, see `errors`) or business rule",
    "401": "Not authenticated / token invalid or expired",
    "403": "Forbidden: missing permission, store not active, read-only…",
    "404": "Not found",
    "409": "Conflict with current state (e.g. insufficient_stock)",
    "429": "Too many requests",
}


class AutoSchema(openapi.AutoSchema):
    """Adds the problem-details error responses to every operation."""

    def _get_response_bodies(self, direction="response"):
        responses = super()._get_response_bodies(direction)
        for code, description in ERROR_STATUSES.items():
            if code == "401" and not self.get_auth():
                continue
            responses.setdefault(
                code,
                self._get_response_for_code(
                    OpenApiResponse(response=ProblemSerializer, description=description), code
                ),
            )
        for code in ERROR_STATUSES:
            if code in responses:
                content = responses[code].get("content", {})
                if "application/json" in content:
                    content["application/problem+json"] = content.pop("application/json")
        return responses
