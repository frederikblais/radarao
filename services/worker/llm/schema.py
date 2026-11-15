"""Conversion des modèles Pydantic en JSON Schema compatible avec les sorties structurées.

Contraintes de l'API : pas de schémas récursifs, `additionalProperties: false`, pas de bornes
numériques ni de longueurs de chaîne (elles sont validées par Pydantic côté code).
"""

from typing import Any

from pydantic import BaseModel

_UNSUPPORTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "maxItems",
    "title",
    "default",
    "examples",
}


def _clean(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in _UNSUPPORTED:
                continue
            if k == "minItems" and v not in (0, 1):
                continue
            if k == "properties" and isinstance(v, dict):
                out[k] = {pk: _clean(pv) for pk, pv in v.items()}  # ne pas filtrer les noms de champs
            else:
                out[k] = _clean(v)
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}).keys())
        return out
    if isinstance(node, list):
        return [_clean(x) for x in node]
    return node


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema(mode="validation")
    cleaned: dict[str, Any] = _clean(schema)
    _assert_not_recursive(cleaned)
    return cleaned


def _assert_not_recursive(schema: dict[str, Any]) -> None:
    defs = schema.get("$defs", {})

    def refs(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            if "$ref" in node:
                found.add(node["$ref"].split("/")[-1])
            for v in node.values():
                found |= refs(v)
        elif isinstance(node, list):
            for v in node:
                found |= refs(v)
        return found

    for name, d in defs.items():
        seen: set[str] = set()
        stack = list(refs(d))
        while stack:
            r = stack.pop()
            if r == name:
                raise ValueError(f"Schéma récursif interdit : {name}")
            if r not in seen and r in defs:
                seen.add(r)
                stack.extend(refs(defs[r]))
