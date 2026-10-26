#!/usr/bin/env python3
"""Read-only, standard-library inventory for the AP1/C3 model migration.

No network, vehicle messages, panda access, process control, or file writes.
Only explicitly listed device files and parameters are read.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess


PARAMETER_NAMES = ("TinklaAutopilotDisabled",)
MODEL_NAMES = ("supercombo.thneed", "supercombo_metadata.pkl")


def read_text(path, limit=16384):
  try:
    with path.open("rb") as stream:
      data = stream.read(limit)
    return data.decode("utf-8", errors="replace").replace("\x00", "").strip()
  except (OSError, ValueError):
    return None


def file_identity(path, include_hash=False):
  try:
    result = {"size_bytes": path.stat().st_size}
    if include_hash:
      digest = hashlib.sha256()
      with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
          digest.update(block)
      result["sha256"] = digest.hexdigest()
    return result
  except OSError:
    return None


def git_output(repo, arguments):
  env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
  try:
    result = subprocess.run(
      ["git", "-c", "core.fsmonitor=false", "-C", str(repo)] + arguments,
      capture_output=True, text=True, timeout=10, check=False, env=env,
    )
    return result.stdout.strip() if result.returncode == 0 else None
  except (OSError, subprocess.TimeoutExpired):
    return None


def inventory(fs_root, repo, include_hash=False, include_git=True):
  fs_root, repo = Path(fs_root), Path(repo)

  def device_path(name):
    return fs_root / name.lstrip("/")

  system = {}
  for key, filename in (
    ("agnos_version_file", "/VERSION"),
    ("os_release", "/etc/os-release"),
    ("device_tree_model", "/proc/device-tree/model"),
    ("soc_machine", "/sys/devices/soc0/machine"),
    ("soc_family", "/sys/devices/soc0/family"),
    ("soc_id", "/sys/devices/soc0/soc_id"),
    ("kernel_release", "/proc/sys/kernel/osrelease"),
  ):
    value = read_text(device_path(filename))
    if value is not None:
      system[key] = value
  memory = read_text(device_path("/proc/meminfo")) or ""
  memory_match = re.search(r"^MemTotal:\s+(\d+)\s+kB", memory, re.MULTILINE)
  if memory_match:
    system["mem_total_kib"] = int(memory_match.group(1))
  system["markers"] = [name for name in ("TICI", "EON") if device_path(name).exists()]

  code = {}
  version = read_text(repo / "common/version.h") or ""
  version_match = re.search(r'#define\s+COMMA_VERSION\s+"([^"]+)"', version)
  if version_match:
    code["comma_version"] = version_match.group(1)
  launch = read_text(repo / "launch_env.sh") or ""
  agnos_match = re.search(r'AGNOS_VERSION\s*=\s*["\x27]([^"\x27]+)', launch)
  if agnos_match:
    code["requested_agnos_version"] = agnos_match.group(1)
  if include_git:
    for name, arguments in (
      ("commit", ["rev-parse", "HEAD"]),
      ("branch", ["symbolic-ref", "--quiet", "--short", "HEAD"]),
    ):
      value = git_output(repo, arguments)
      if value is not None:
        code[name] = value
    status = git_output(repo, ["status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all"])
    if status is not None:
      code["tracked_changes_count"] = len(status.splitlines())

  params = {}
  for name in PARAMETER_NAMES:
    value = read_text(device_path("/data/params/d") / name, limit=128)
    if value is not None:
      params[name] = value

  models = {}
  for name in MODEL_NAMES:
    identity = file_identity(repo / "selfdrive/modeld/models" / name, include_hash)
    if identity is not None:
      models[name] = identity

  video_names = []
  for path in sorted(device_path("/sys/class/video4linux").glob("*/name")):
    value = read_text(path, limit=256)
    if value:
      video_names.append(value)

  usb_devices = []
  for path in sorted(device_path("/sys/bus/usb/devices").glob("*")):
    vendor = read_text(path / "idVendor", limit=16)
    product = read_text(path / "idProduct", limit=16)
    if vendor and product:
      usb_devices.append({"vendor_id": vendor, "product_id": product})

  return {
    "format_version": 1,
    "system": system,
    "code": code,
    "selected_parameters": params,
    "models": models,
    "video_device_names": video_names,
    "usb_product_ids": usb_devices,
    "notes": [
      "Missing fields are unknown, not proof of incompatibility.",
      "No panda firmware/safety state was queried; USB IDs do not establish firmware compatibility.",
      "No serial numbers, VIN, network addresses, git remotes, credentials, or complete parameter dump collected.",
    ],
  }


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--fs-root", default="/", help="Filesystem root; override only for offline fixtures")
  parser.add_argument("--repo", default="/data/openpilot", help="Installed openpilot directory")
  parser.add_argument("--hash-models", action="store_true", help="Also hash the selected current model files")
  parser.add_argument("--skip-git", action="store_true", help="Skip local, read-only git commands")
  args = parser.parse_args()
  report = inventory(args.fs_root, args.repo, args.hash_models, not args.skip_git)
  report["python_version"] = platform.python_version()
  report["machine"] = platform.machine()
  print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
  main()
