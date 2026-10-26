import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from device_inventory import inventory


class DeviceInventoryTests(unittest.TestCase):
  def test_incomplete_device_reports_unknown_without_running_commands(self):
    with tempfile.TemporaryDirectory() as directory, patch("device_inventory.subprocess.run") as command:
      report = inventory(directory, Path(directory) / "missing", include_git=False)
      self.assertEqual(report["code"], {})
      self.assertEqual(report["models"], {})
      self.assertNotIn("agnos_version_file", report["system"])
      command.assert_not_called()

  def test_allowlist_omits_private_parameters_and_usb_serial(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      params = root / "data/params/d"
      params.mkdir(parents=True)
      (params / "TinklaAutopilotDisabled").write_text("1")
      (params / "AccessToken").write_text("secret-test-token")
      (params / "CarVin").write_text("private-test-vin")
      usb = root / "sys/bus/usb/devices/1-1"
      usb.mkdir(parents=True)
      (usb / "idVendor").write_text("bbaa")
      (usb / "idProduct").write_text("ddcc")
      (usb / "serial").write_text("private-test-serial")
      report = inventory(root, root / "repo", include_git=False)
      encoded = json.dumps(report)
      for private_value in ("secret-test-token", "private-test-vin", "private-test-serial"):
        self.assertNotIn(private_value, encoded)
      self.assertEqual(report["selected_parameters"], {"TinklaAutopilotDisabled": "1"})
      self.assertEqual(report["usb_product_ids"], [{"vendor_id": "bbaa", "product_id": "ddcc"}])

  def test_fixture_version_and_optional_hash_do_not_modify_files(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      repo = root / "repo"
      (repo / "common").mkdir(parents=True)
      (repo / "common/version.h").write_text('#define COMMA_VERSION "0.9.6-61"\n')
      (repo / "launch_env.sh").write_text('export AGNOS_VERSION="9.1"\n')
      (root / "VERSION").write_text("9.1\n")
      model_dir = repo / "selfdrive/modeld/models"
      model_dir.mkdir(parents=True)
      model = model_dir / "supercombo.thneed"
      model.write_bytes(b"fixture-model")
      before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
      report = inventory(root, repo, include_hash=True, include_git=False)
      after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
      self.assertEqual(before, after)
      self.assertEqual(report["code"]["comma_version"], "0.9.6-61")
      self.assertEqual(report["code"]["requested_agnos_version"], "9.1")
      self.assertEqual(report["system"]["agnos_version_file"], "9.1")
      self.assertEqual(report["models"]["supercombo.thneed"]["sha256"], hashlib.sha256(b"fixture-model").hexdigest())


if __name__ == "__main__":
  unittest.main()
