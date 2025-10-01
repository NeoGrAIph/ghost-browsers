# Задание: camoufox_worker

## Цель
Исполнитель фоновых задач для GhostBrowsers. Поддержать **два режима**: нативный Camoufox (короткие задачи без VNC) и оркестрацию через Gateway/Runner.

## Требования (MVP)
1) **Интерфейс задач** (`worker/jobs.py`): описание Job, параметры (url, proxy, таймауты), результат (статус, метрики).
2) **Native‑runner** (`worker/runner_native.py`): функция `run_job(job)` с использованием Camoufox (`headless=os.getenv('CAMOUFOX_HEADLESS','virtual')`, `geoip=True` при прокси).
3) **Orchestrator‑runner** (`worker/runner_orch.py`): заглушки вызовов Gateway (`POST /sessions`, `/delete`, `/proxy`).
4) **Entrypoint** (`worker/main.py`): CLI `python -m worker.main run --mode=native --url=...` (без очереди); возврат exit‑code по статусу.
5) **Тесты**: 
   - smoke‑тест наличия файлов и `AGENT_NOTES.md`;
   - unit‑заглушка `run_job()` (без настоящей сети, моки);
   - тест CLI парсинга.
6) **Документация**: обновить `AGENT_NOTES.md` (Interfaces/Decisions/TODO/How to Test).

## Next
- Подключить очередь (Redis/AMQP) и расписание; job‑репорты в Prometheus; ретраи/идемпотентность.
