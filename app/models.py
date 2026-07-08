"""Database models for tracking submissions and templates."""

from datetime import datetime, timezone

from app import db


class JobSubmission(db.Model):
    """Record of a job submission made through the web UI."""

    __tablename__ = "job_submissions"

    id = db.Column(db.Integer, primary_key=True)
    cluster_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, default="Untitled Job")
    submit_description = db.Column(db.Text, nullable=False)  # JSON string
    num_procs = db.Column(db.Integer, nullable=False, default=1)
    submitted_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    log_dir = db.Column(db.String(512), nullable=True)
    output_dir = db.Column(db.String(512), nullable=True)
    owner = db.Column(db.String(128), nullable=True)
    cmd = db.Column(db.Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cluster_id": self.cluster_id,
            "name": self.name,
            "submit_description": self.submit_description,
            "num_procs": self.num_procs,
            "submitted_at": self.submitted_at.isoformat() + "Z",
            "log_dir": self.log_dir,
            "output_dir": self.output_dir,
            "owner": self.owner,
            "cmd": self.cmd,
        }
