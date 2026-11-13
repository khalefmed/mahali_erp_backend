"""Validation of product / variant attributes against their category's schema."""

from rest_framework.exceptions import ValidationError

TYPES = {"choice", "text", "number", "boolean"}
LEVELS = {"product", "variant"}


def validate_schema(schema) -> list[dict]:
    if not isinstance(schema, list):
        raise ValidationError({"attribute_schema": "Must be a list."}, code="invalid")
    keys = set()
    for index, item in enumerate(schema):
        where = f"attribute_schema.{index}"
        if not isinstance(item, dict) or not item.get("key") or not item.get("label"):
            raise ValidationError({where: "key and label are required."}, code="invalid")
        if item.get("type") not in TYPES:
            raise ValidationError({where: f"type must be one of {sorted(TYPES)}."}, code="invalid")
        if item.get("level", "product") not in LEVELS:
            raise ValidationError({where: "level must be product or variant."}, code="invalid")
        if item["type"] == "choice" and not item.get("options"):
            raise ValidationError({where: "choice needs options."}, code="invalid")
        if item["key"] in keys:
            raise ValidationError({where: "duplicate key."}, code="invalid")
        keys.add(item["key"])
    return schema


def validate_attributes(schema: list[dict], values: dict, level: str, field: str) -> dict:
    """Returns cleaned values. Unknown keys and wrong types are rejected."""
    if not isinstance(values, dict):
        raise ValidationError({field: "Must be an object."}, code="invalid")
    definitions = {d["key"]: d for d in schema if d.get("level", "product") == level}
    errors, cleaned = {}, {}
    for key in values:
        if key not in definitions:
            errors[f"{field}.{key}"] = ["Unknown attribute for this category."]
    for key, definition in definitions.items():
        value = values.get(key)
        if value in (None, ""):
            if definition.get("required"):
                errors[f"{field}.{key}"] = ["This attribute is required."]
            continue
        kind = definition["type"]
        if kind == "choice" and value not in definition["options"]:
            errors[f"{field}.{key}"] = [f"Choose one of: {', '.join(definition['options'])}."]
        elif kind == "number" and not isinstance(value, int | float):
            errors[f"{field}.{key}"] = ["Must be a number."]
        elif kind == "boolean" and not isinstance(value, bool):
            errors[f"{field}.{key}"] = ["Must be true or false."]
        elif kind == "text" and not isinstance(value, str):
            errors[f"{field}.{key}"] = ["Must be text."]
        cleaned[key] = value
    if errors:
        raise ValidationError(errors, code="invalid_attribute")
    return cleaned
