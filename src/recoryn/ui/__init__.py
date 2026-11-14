"""Optional PySide6 desktop; importing Recoryn never starts Qt or opens devices."""


def launch(root: str | None = None) -> int:
    from recoryn.ui.main import run

    return run(root)
