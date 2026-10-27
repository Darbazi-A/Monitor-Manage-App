"""
The installed program's entry point (what PyInstaller builds the .exe from).

The same .exe is two things: the stage desk, and - started by the DJ desk with
--dj-decoder - its audio decoder process, which has no window and talks over
pipes. Run from source, main.py and dj_decoder.py are started directly instead.
"""
import sys


def run() -> int:
    if "--dj-decoder" in sys.argv[1:]:
        import dj_decoder
        return dj_decoder.main()
    if "--selftest" in sys.argv[1:]:
        import selftest                     # first: it sets up its own settings and files
        at = sys.argv.index("--selftest")
        return selftest.run(sys.argv[at + 1] if at + 1 < len(sys.argv) else "selftest.json")
    import main
    return main.main()


if __name__ == "__main__":
    sys.exit(run())
