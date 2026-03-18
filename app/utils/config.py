from app.db.mongo import app_settings

DEFAULT_CONFIG = {
    "upload_cost": 10,
    "page_cost": 1,
    "default_limit": 5,
    "base_price_kobo": 5000,
}

DEFAULT_PLANS = {
    "starter": {"credits": 50, "price_ngn": 1000, "page_limit": 50},
    "professional": {"credits": 120, "price_ngn": 2000, "page_limit": 200},
    "mastery": {"credits": 500, "price_ngn": 5000, "page_limit": 5000},
}


def get_app_config():
    config = app_settings.find_one({"type": "global_config"})
    if not config:
        return DEFAULT_CONFIG

    # Merge with defaults to ensure all keys exist
    merged = DEFAULT_CONFIG.copy()
    for k, v in config.items():
        if k in merged:
            merged[k] = v
    return merged


def get_app_plans():
    plans_cursor = app_settings.find({"type": "plan"})
    plans = list(plans_cursor)

    if not plans:
        return DEFAULT_PLANS

    result = {}
    for p in plans:
        plan_id = p["plan_id"]
        result[plan_id] = {
            "credits": p.get("credits", 0),
            "price_ngn": p.get("price_ngn", 0),
            "page_limit": p.get("page_limit", 0),
        }

    # Ensure all default plans exist (merge)
    for p_id, p_data in DEFAULT_PLANS.items():
        if p_id not in result:
            result[p_id] = p_data

    return result


def get_plan_page_limit(plan_id: str):
    plans = get_app_plans()
    if plan_id in plans:
        return plans[plan_id]["page_limit"]

    config = get_app_config()
    return config["default_limit"]
