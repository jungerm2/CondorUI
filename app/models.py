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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "cluster_id": self.cluster_id,
            "name": self.name,
            "submit_description": self.submit_description,
            "num_procs": self.num_procs,
            "submitted_at": self.submitted_at.isoformat() + "Z",
            "log_dir": self.log_dir,
        }


class SubmitTemplate(db.Model):
    """A saved submit description that can be reused."""

    __tablename__ = "submit_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    submit_data = db.Column(db.Text, nullable=False)  # JSON string
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "submit_data": self.submit_data,
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
        }
