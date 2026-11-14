"""Frozen diagnostic/installation entry. Never parse spawn arguments first."""

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    from recoryn_release import main

    raise SystemExit(main(gui=False))
