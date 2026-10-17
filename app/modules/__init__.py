"""Business modules. Each one is a Flow (app/services/flow.py) with its own tables, steps and texts.

The core never imports a module: app/utils/dependencies.py registers them by `store_settings.business_type`.
"""

import importlib
import pkgutil


def import_models() -> None:
    """Imports every module's models.py, so their tables join Base.metadata (migrations, tests)."""
    for module in pkgutil.iter_modules(__path__):
        if module.ispkg:
            importlib.import_module(f"{__name__}.{module.name}.models")
