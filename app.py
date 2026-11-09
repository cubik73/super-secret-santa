"""Entry point for the packaged executable.

  secret-santa                 open the form in your browser (what double-clicking does)
  secret-santa cli [args]      command-line version, e.g. `secret-santa cli people.csv --test`
"""
import sys

import secret_santa
import web


def main() -> None:
    # Some Windows consoles can't show emoji/✓; replace instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = sys.argv[1:]
    if args and args[0] == "cli":
        sys.exit(secret_santa.main(args[1:]))
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        print("Browser options: --port N, --no-browser")
        return
    web.main(args)


if __name__ == "__main__":
    main()
