"""Display metadata only. Never use a label as a model identity or grant."""

UNNAMED_MODEL = "未命名模型"


def model_display_name(model):
    name = model.get("name") if isinstance(model, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else UNNAMED_MODEL


def catalog_model_name(catalog, model_id, version):
    # A missing version must not silently select the latest release's name.
    if not model_id or not version:
        return UNNAMED_MODEL
    try:
        return model_display_name(catalog.get(model_id, version))
    except (KeyError, ValueError, OSError):
        return UNNAMED_MODEL
