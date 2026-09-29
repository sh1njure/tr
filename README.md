# TV Snapshot → Notion

Снимает снапшоты TradingView (Alt+S) по ТФ из `config.json` в уже открытом Chrome
(работает и в Bar Replay) и вписывает ссылки в пустые колонки скринов последней записи в Notion.

## Установка (Windows)
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # вписать NOTION_TOKEN
```
Интеграцию Notion нужно добавить в базу (••• → Connections).
Playwright-браузеры качать не надо — подключаемся к твоему Chrome.

## Запуск
1. `chrome_tv.bat` — Chrome с отдельным профилем и портом 9222. Залогиниться в TV, открыть график.
2. Проверка по шагам:
   - `python step1_snapshots.py` — снапшоты, ссылки в консоль.
   - `python step2_notion.py [EURUSD]` — схема базы + найденная запись.
3. `run_app.bat` (или `python app.py`) — UI.

## Notion
В базе должны быть URL-колонки из `config.json` → `timeframes[].column`
(по умолчанию `W, D, 4H, 1H, 15m, 5m`). Если их нет — прога покажет схему и что создать.
Имена колонок пары/даты/сетапа — `config.json` → `notion`.

## Логи
`logs/tvsnap_YYYYMMDD.log`
