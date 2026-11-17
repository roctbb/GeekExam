"""Operator commands run inside the deployed Guard container."""
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import secrets

import click
from flask import current_app

from .models import db, AuditEvent, Room, Router, Segment
from .security import digest, now


def register(app):
    @app.cli.command("bootstrap-router")
    @click.option("--room", required=True)
    @click.option("--name", required=True)
    @click.option("--interface", default="Bridge0")
    @click.option("--output", type=click.Path(), required=True)
    def bootstrap_router(room, name, interface, output):
        """Create a room/router and an enrollment file; never enable filtering."""
        if not re.fullmatch(r"Bridge[0-9]{1,2}", interface) or not 1 <= len(room) <= 100 or not 1 <= len(name) <= 100:
            raise click.ClickException("Invalid room, router or interface")
        path = Path(output)
        # Do not replace a previous credential file by accident.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            cabinet = db.session.execute(db.select(Room).where(Room.name == room)).scalar_one_or_none()
            if cabinet is None:
                cabinet = Room(name=room, resources=[{"ip":"195.133.49.12","port":443}])
                db.session.add(cabinet)
                db.session.flush()
            router = db.session.execute(db.select(Router).where(Router.room_id == cabinet.id, Router.name == name)).scalar_one_or_none()
            if router is None:
                router = Router(room_id=cabinet.id, name=name)
                db.session.add(router)
                db.session.flush()
                db.session.add(Segment(router_id=router.id, name="Wi-Fi · наблюдение", interface=interface, purpose="student"))
            elif router.token_digest:
                raise click.ClickException("Router already has an agent; rotate its enrollment from the administrator UI")
            code = secrets.token_urlsafe(32)
            router.enroll_digest, router.enroll_expires_at = digest(code), now()+timedelta(minutes=10)
            db.session.add(AuditEvent(room_id=cabinet.id, event="router.provisioned", target_id=router.id, details={"mode":"observe"}))
            db.session.commit()
            with os.fdopen(descriptor, "w") as stream:
                descriptor = None
                json.dump({"code":code,"room_id":cabinet.id,"router_id":router.id,
                           "guard_url":current_app.config["PUBLIC_URL"],"interfaces":[interface]}, stream)
            click.echo("Router provisioned in observation mode; enrollment saved to the private output file.")
        except BaseException:
            db.session.rollback()
            if descriptor is not None:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise
