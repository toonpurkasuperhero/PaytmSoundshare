"""Admin CLI.

    python -m app.cli create-admin --phone 98XXXXXXXX
    python -m app.cli set-password --phone 98XXXXXXXX

The password is prompted for (never pass it on the command line).
"""
from __future__ import annotations

import argparse
import getpass
import sys

from fastapi import HTTPException
from sqlalchemy import select

from . import auth
from .db import Base, engine, session_scope
from .models import User
from .money import new_id


def _password() -> str:
    pw = getpass.getpass("Password (min 8 chars): ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    auth.validate_password(pw)
    return pw


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("create-admin", "set-password"):
        p = sub.add_parser(name)
        p.add_argument("--phone", required=True)
    sub.add_parser("seed-demo", help="create demo merchants/advertisers (AI-classified catalog, AI ads)")
    sub.add_parser("remove-demo", help="delete all demo accounts and their data")
    a = ap.parse_args()
    Base.metadata.create_all(engine)
    from . import migrate
    migrate.run()
    if a.cmd in ("seed-demo", "remove-demo"):
        import logging
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
        from . import demo
        if a.cmd == "remove-demo":
            try:
                print("Removed:", demo.remove())
            except RuntimeError as e:
                sys.exit(str(e))
            return
        print(f"Creating demo accounts (password for all: {demo.DEMO_PASSWORD}) ...")
        for r in demo.seed():
            print(f"\n[{r['status']}] {r['role']}: {r['name']}  login {r['phone']}")
            for k in ("catalog", "device_id", "device_token", "wallet", "campaign", "ad"):
                if r.get(k):
                    print(f"    {k}: {r[k]}")
        print("\nRemove everything later with: python -m app.cli remove-demo")
        return
    try:
        phone = auth.normalize_phone(a.phone)
        with session_scope() as db:
            u = db.scalars(select(User).where(User.phone == phone)).first()
            if a.cmd == "create-admin":
                if u:
                    sys.exit(f"{phone} already has a {u.role} account")
                db.add(User(id=new_id("U", 5), phone=phone, password_hash=auth.hash_password(_password()),
                            role="admin", name="SoundShare Admin"))
                print(f"Admin {phone} created")
            else:
                if not u:
                    sys.exit(f"No account for {phone}")
                u.password_hash = auth.hash_password(_password())
                print(f"Password updated for {phone} ({u.role})")
    except HTTPException as e:
        sys.exit(str(e.detail))


if __name__ == "__main__":
    main()
