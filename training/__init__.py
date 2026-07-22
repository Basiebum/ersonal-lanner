from flask import Blueprint

training_bp = Blueprint(
    "training",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)

from . import routes  # noqa: E402,F401  (import at bottom to avoid circular import)
