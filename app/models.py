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
    log_path = db.Column(db.String(1024), nullable=True)  # Resolved UserLog path
    out_path = db.Column(db.String(1024), nullable=True)  # Resolved Out (stdout) path
    err_path = db.Column(db.String(1024), nullable=True)  # Resolved Err (stderr) path
    output_destination = db.Column(
        db.String(1024), nullable=True
    )  # Resolved output_destination
    transfer_output_remaps = db.Column(
        db.Text, nullable=True
    )  # Resolved transfer_output_remaps
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
            "log_path": self.log_path,
            "out_path": self.out_path,
            "err_path": self.err_path,
            "output_destination": self.output_destination,
            "transfer_output_remaps": self.transfer_output_remaps,
            "owner": self.owner,
            "cmd": self.cmd,
        }
