"""Vault boot-time default resolution.

TEPHRA_VAULT is an explicit, this-launch override (set by --vault or the
desktop launcher) and always wins. TEPHRA_DEFAULT_VAULT is a lower-priority
bootstrap default, consulted only when nothing else applies -- a container
always has some environment variable set for its default vault, and
collapsing both into TEPHRA_VAULT permanently blocked "the last vault you
had open wins" (app/main.py's lifespan) under any deployment that sets
one, which is exactly what docker-compose.yml did.

Each case runs in a fresh subprocess: vault.VAULT is resolved once, at
import time, from the environment, so re-importing in this same process
would just return the already-cached module.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PY = os.path.join(ROOT, ".venv", "bin", "python")


def boot(**overrides):
    env = {k: v for k, v in os.environ.items()
           if k not in ("TEPHRA_VAULT", "TEPHRA_DEFAULT_VAULT")}
    env["PYTHONPATH"] = ROOT
    env.update(overrides)
    out = subprocess.run([PY, "-c", "from app import vault; print(vault.VAULT)"],
                          env=env, cwd=ROOT, capture_output=True, text=True)
    return out.stdout.strip(), out.stderr


ok = fail = 0
def ck(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  PASS  {label} {extra}")
    else:    fail += 1; print(f"  FAIL  {label} {extra}")

print("── vault.py's own boot-time default ──")
out, err = boot()
ck("neither set falls back to the generic /vault", out == "/vault", (out, err))

out, err = boot(TEPHRA_DEFAULT_VAULT="/vaults/Tephra")
ck("bootstrap default is used when nothing else applies", out == "/vaults/Tephra", (out, err))

out, err = boot(TEPHRA_VAULT="/vaults/FB Study", TEPHRA_DEFAULT_VAULT="/vaults/Tephra")
ck("an explicit override always wins over the bootstrap default",
   out == "/vaults/FB Study", (out, err))

out, err = boot(TEPHRA_VAULT="/vaults/FB Study")
ck("an explicit override works with no bootstrap default set",
   out == "/vaults/FB Study", (out, err))

print(f"\n{'='*46}\n  {ok} passed, {fail} failed\n{'='*46}")
raise SystemExit(1 if fail else 0)
