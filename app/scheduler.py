from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def add_monitor_job(monitor_id: int, interval_minutes: int):
    job_id = f"monitor_{monitor_id}"
    # Remove existing job if any
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=_run_check,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id=job_id,
        args=[monitor_id],
        next_run_time=datetime.now(timezone.utc),  # run immediately on add
        misfire_grace_time=300,
    )
    logger.info("Scheduled job %s every %d min", job_id, interval_minutes)


def remove_monitor_job(monitor_id: int):
    job_id = f"monitor_{monitor_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Removed job %s", job_id)


def get_next_run(monitor_id: int) -> datetime | None:
    job = scheduler.get_job(f"monitor_{monitor_id}")
    if job and job.next_run_time:
        return job.next_run_time
    return None


def _run_check(monitor_id: int):
    """Executed by APScheduler in a background thread."""
    from app.database import SessionLocal
    from app.models import Monitor
    from app.scraper import scrape_product
    from app.notifier import send_whatsapp, build_in_stock_message, build_back_out_of_stock_message

    db = SessionLocal()
    try:
        monitor = db.get(Monitor, monitor_id)
        if not monitor or not monitor.is_active or monitor.got_it:
            remove_monitor_job(monitor_id)
            return

        previous_status = monitor.status
        result = scrape_product(monitor.url)

        now = datetime.now(timezone.utc)
        monitor.last_checked = now
        monitor.price = result.price
        monitor.error_message = result.error

        if result.error:
            monitor.status = "error"
        elif result.in_stock:
            monitor.status = "in_stock"
        else:
            monitor.status = "out_of_stock"

        # Update next check time
        next_run = get_next_run(monitor_id)
        if next_run:
            monitor.next_check = next_run

        # Notify on transition: out_of_stock / unknown → in_stock
        if monitor.status == "in_stock" and previous_status != "in_stock":
            msg = build_in_stock_message(monitor.name, monitor.url, monitor.price)
            send_whatsapp(monitor.phone_number, msg)
            logger.info("Notified %s: %s is IN STOCK", monitor.phone_number, monitor.name)

        # Notify if it went back out of stock (optional courtesy alert)
        elif monitor.status == "out_of_stock" and previous_status == "in_stock":
            msg = build_back_out_of_stock_message(monitor.name)
            send_whatsapp(monitor.phone_number, msg)

        db.commit()
    except Exception:
        logger.exception("Error in check job for monitor %d", monitor_id)
        db.rollback()
    finally:
        db.close()
