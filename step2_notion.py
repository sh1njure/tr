"""Шаг 2: поиск последней записи с пустыми колонками скринов. Использование: python step2_notion.py [ПАРА]"""
import sys

from tvsnap.config import load_config, notion_token, setup_logging
from tvsnap.notion_db import NotionDB, NotionError


def main() -> int:
    log = setup_logging()
    cfg = load_config()
    pair = sys.argv[1] if len(sys.argv) > 1 else None
    db = NotionDB(notion_token(), cfg)
    print("Схема базы:\n" + db.schema_text())
    try:
        rec = db.find_latest(pair)
    except NotionError as e:
        log.error("%s", e)
        return 1
    if not rec:
        print("Нет записи с пустыми колонками скринов" + (f" для {pair}" if pair else ""))
        return 0
    print(f"\nЗапись: {rec.summary()}\n{rec.url}\nПустые колонки: {rec.empty_columns}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
