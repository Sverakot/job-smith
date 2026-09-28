import argparse
import logging
import sys
from pathlib import Path

from . import db
from .config import load_settings
from .llm import LLMError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="job-smith", description="Local LLM-assisted job search")
    ap.add_argument("--config", type=Path, help="settings.yaml path")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the database")
    p = sub.add_parser("profile", help="build profile.json/md from your CV")
    p.add_argument("cv", type=Path)
    p.add_argument("--prefs", default="", help='free-text preferences, e.g. "hybrid Tel Aviv, no sales"')
    p.add_argument("--force", action="store_true", help="overwrite an existing profile.json")
    sub.add_parser("discover", help="fetch jobs from configured sources")
    m = sub.add_parser("match", help="filter + score unevaluated jobs")
    m.add_argument("--limit", type=int)
    m.add_argument("--rescore", action="store_true", help="re-evaluate everything")
    sub.add_parser("report", help="write the Markdown report")
    r = sub.add_parser("run", help="discover + match + report (for nightly use)")
    r.add_argument("--limit", type=int)
    sub.add_parser("status", help="show recent runs")

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("job_smith")

    settings = load_settings(args.config)
    conn = db.connect(settings.db_path)

    # Imported lazily so `init`/`status` work before optional pieces are configured.
    from .agents.matcher import match
    from .agents.profile import build_profile
    from .report import build_report
    from .workers.ats_boards import discover

    try:
        if args.cmd == "init":
            log.info("Database ready at %s", settings.db_path)
        elif args.cmd == "profile":
            prof = build_profile(settings, args.cv, args.prefs, args.force)
            log.info("Wrote %s and %s. Review and edit the JSON before matching.",
                     settings.profile_json, settings.profile_md)
            log.info("Targets: %s", ", ".join(prof.target_titles))
        elif args.cmd == "discover":
            log.info("Discovery: %s", discover(settings, conn))
        elif args.cmd == "match":
            log.info("Matching: %s", match(settings, conn, args.limit, args.rescore))
        elif args.cmd == "report":
            log.info("Report: %s", build_report(settings, conn))
        elif args.cmd == "run":
            log.info("Discovery: %s", discover(settings, conn))
            log.info("Matching: %s", match(settings, conn, args.limit))
            log.info("Report: %s", build_report(settings, conn))
        elif args.cmd == "status":
            for row in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 20"):
                print(f"{row['started_at']}  {row['kind']:<9} {row['status']:<7} "
                      f"{(row['target'] or ''):<28} found={row['jobs_found']} new={row['jobs_new']} "
                      f"{row['error'] or ''}")
    except (FileNotFoundError, FileExistsError, ValueError, LLMError) as e:
        log.error("%s", e)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
