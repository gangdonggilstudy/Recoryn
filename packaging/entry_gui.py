"""Frozen GUI entry: worker dispatch precedes all Qt/application imports."""

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    from recoryn_release import main

    raise SystemExit(main(gui=True))
