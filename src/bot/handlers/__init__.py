import importlib.util
import os
from pathlib import Path

from aiogram import Router

from src.bot.handlers import primary


def find_routers(folder_path):
    routers = [primary.router]
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".py") and file not in ("__init__.py", "primary.py"):
                module_path = os.path.join(root, file)
                module_name = os.path.splitext(file)[0]

                spec = importlib.util.spec_from_file_location(module_name, module_path)
                assert spec is not None and spec.loader is not None

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                if hasattr(module, "router"):
                    routers.append(getattr(module, "router"))
    return routers


found_routers = find_routers(Path(__file__).parent)
root_router = Router()
root_router.include_routers(*found_routers)
