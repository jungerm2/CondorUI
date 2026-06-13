"""Database models for tracking submissions, templates, and uploaded files."""

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


class UploadedFile(db.Model):
    """A file uploaded through the web UI, optionally staged to OSDF."""

    __tablename__ = "uploaded_files"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    local_path = db.Column(db.String(512), nullable=True)  # null if moved to OSDF
    osdf_path = db.Column(db.String(512), nullable=True)   # null if local only
    size = db.Column(db.Integer, nullable=False, default=0)
    uploaded_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        from flask import current_app

        # Compute the URI
        if self.osdf_path:
            base_uri = current_app.config.get("OSDF_BASE_URI", "osdf:///")
            # Files are stored in OSDF_ROOT_PATH/uploads/<filename>
            uri = base_uri.rstrip("/") + "/uploads/" + self.filename
        elif self.local_path:
            uri = self.local_path
        else:
            uri = ""

        return {
            "id": self.id,
            "filename": self.filename,
            "original_name": self.original_name,
            "local_path": self.local_path,
            "osdf_path": self.osdf_path,
            "uri": uri,
            "size": self.size,
            "uploaded_at": self.uploaded_at.isoformat() + "Z",
        }


class ContainerImage(db.Model):
    """A container image (.sif) stored in the OSDF containers directory."""

    __tablename__ = "container_images"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False, unique=True)
    source = db.Column(db.String(512), nullable=True)  # e.g., "docker://ubuntu:latest"
    size = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        from flask import current_app

        base_uri = current_app.config.get("OSDF_BASE_URI", "osdf:///")
        uri = base_uri.rstrip("/") + "/containers/" + self.filename

        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "source": self.source,
            "uri": uri,
            "size": self.size,
            "created_at": self.created_at.isoformat() + "Z",
        }
