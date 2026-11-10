"""Operational CLI: admin bootstrap and collector token management.

Run from the ``backend`` directory:

    python -m app.cli create-admin --email admin@example.com --password secret123
    python -m app.cli create-collector-token --name chrome-extension
    python -m app.cli list-collector-tokens
    python -m app.cli revoke-collector-token --name chrome-extension
"""
from __future__ import annotations

import argparse
import secrets
import sys
import uuid

from sqlalchemy import select

from app import models  # noqa: F401 - ensure every model is registered
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import token_digest
from app.core.timeutils import utcnow
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_sessionmaker
from app.models.collector import CollectorToken
from app.models.enums import Role
from app.services import settings_service, user_service


def _session():
    settings = get_settings()
    if not settings.is_production:
        Base.metadata.create_all(get_engine())
    return get_sessionmaker()()


def cmd_create_admin(args: argparse.Namespace) -> int:
    with _session() as session:
        existing = user_service.get_user_by_email(session, args.email)
        if existing is not None:
            print(f"A user with {args.email} already exists (role={existing.role}).")
            return 1
        user = user_service.create_user(
            session,
            name=args.name,
            email=args.email,
            password=args.password,
            role=Role.ADMIN,
        )
        print(f"Created admin {user.email} ({user.id}).")
        return 0


def cmd_create_collector_token(args: argparse.Namespace) -> int:
    raw = args.token or f"col_{secrets.token_urlsafe(32)}"
    digest = token_digest(raw)
    with _session() as session:
        if session.scalar(select(CollectorToken).where(CollectorToken.token_hash == digest)):
            print("A collector token with this value already exists.")
            return 1
        token = CollectorToken(name=args.name, token_hash=digest, is_active=True)
        session.add(token)
        session.commit()
        print(f"Created collector token '{args.name}' ({token.id}).")
        print("Store this token now; it will not be shown again:")
        print(raw)
        return 0


def cmd_list_collector_tokens(_: argparse.Namespace) -> int:
    with _session() as session:
        tokens = session.scalars(select(CollectorToken).order_by(CollectorToken.created_at)).all()
        if not tokens:
            print("No collector tokens.")
            return 0
        for token in tokens:
            state = "ACTIVE" if token.is_active and token.revoked_at is None else "REVOKED"
            last_seen = token.last_seen_at.isoformat() if token.last_seen_at else "never"
            print(f"{token.id}  {token.name:<24} {state:<8} last_seen={last_seen}")
        return 0


def cmd_revoke_collector_token(args: argparse.Namespace) -> int:
    with _session() as session:
        token: CollectorToken | None = None
        if args.id:
            token = session.get(CollectorToken, uuid.UUID(args.id))
        elif args.name:
            token = session.scalar(select(CollectorToken).where(CollectorToken.name == args.name))
        if token is None:
            print("Collector token not found.")
            return 1
        token.is_active = False
        token.revoked_at = utcnow()
        session.commit()
        print(f"Revoked collector token '{token.name}' ({token.id}).")
        return 0


def cmd_seed_settings(_: argparse.Namespace) -> int:
    with _session() as session:
        settings_service.ensure_defaults(session)
        print("Default settings are present.")
        return 0


def cmd_show_settings(_: argparse.Namespace) -> int:
    import json

    with _session() as session:
        print(json.dumps(settings_service.get_all(session), indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="Create an administrator account")
    admin.add_argument("--name", default="Administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--password", required=True)
    admin.set_defaults(func=cmd_create_admin)

    create_token = sub.add_parser("create-collector-token", help="Create a collector API token")
    create_token.add_argument("--name", required=True)
    create_token.add_argument("--token", default=None, help="Provide a fixed token (testing only)")
    create_token.set_defaults(func=cmd_create_collector_token)

    sub.add_parser("list-collector-tokens", help="List collector tokens").set_defaults(
        func=cmd_list_collector_tokens
    )

    revoke = sub.add_parser("revoke-collector-token", help="Revoke a collector token")
    revoke.add_argument("--id")
    revoke.add_argument("--name")
    revoke.set_defaults(func=cmd_revoke_collector_token)

    sub.add_parser("seed-settings", help="Persist default settings").set_defaults(
        func=cmd_seed_settings
    )
    sub.add_parser("show-settings", help="Print effective settings").set_defaults(
        func=cmd_show_settings
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) == "revoke-collector-token" and not (args.id or args.name):
        parser.error("revoke-collector-token requires --id or --name")
    try:
        return int(args.func(args))
    finally:
        dispose_engine()


if __name__ == "__main__":
    sys.exit(main())
