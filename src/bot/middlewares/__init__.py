import importlib.util
import os

from aiogram import BaseMiddleware

preloaded_middlewares = BaseMiddleware.__subclasses__()


def import_module_from_file(file_path):
    module_name = os.path.splitext(os.path.basename(file_path))[0]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def init_middlewares(folder_path):
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".py") and file not in ("__init__.py",):
                file_path = os.path.join(root, file)
                import_module_from_file(file_path)


init_middlewares("src/bot/middlewares")

loaded_middlewares = set(
    mw for mw in BaseMiddleware.__subclasses__() if mw not in preloaded_middlewares
)
