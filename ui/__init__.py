"""UI: главное окно и виджеты холста."""


def __getattr__(name: str):
    if name == "MainWindow":
        from .main_window import MainWindow

        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["MainWindow"]
