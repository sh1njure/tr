"""Шаг 1: подключение к Chrome + снапшоты, ссылки в консоль."""
import sys

from tvsnap.config import load_config, setup_logging
from tvsnap.tv import TVError, TVSnapper


def main() -> int:
    log = setup_logging()
    cfg = load_config()
    try:
        links = TVSnapper(cfg).run(lambda tf, st, d: print(f"[{tf}] {st} {d}"))
    except TVError as e:
        log.error("%s", e)
        return 1
    print("\nРезультат:")
    for item in cfg["timeframes"]:
        print(f"  {item['tf']:>4}: {links.get(item['tf'], 'ПРОПУЩЕН')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
