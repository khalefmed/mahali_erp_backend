from drf_spectacular.extensions import OpenApiAuthenticationExtension


class MerchantJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.MerchantJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}


class ConsoleJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.ConsoleJWTAuthentication"
    name = "consoleJwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Console (Mahali team) token from console/auth/login",
        }
