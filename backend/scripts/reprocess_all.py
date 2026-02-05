from backend.app.db import SessionLocal, init_db
from backend.app import models
from backend.app.services.jobs import enqueue_job

def main():
    init_db()
    db = SessionLocal()
    try:
        arts = db.query(models.Artifact).all()
        for a in arts:
            enqueue_job(db, a.id, "extract_text")
        print(f"enqueued {len(arts)} artifacts")
    finally:
        db.close()

if __name__ == "__main__":
    main()
