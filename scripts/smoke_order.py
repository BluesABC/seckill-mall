"""Start the built S0 jar briefly, verify health semantics, then stop only that process."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
jar = Path(os.environ.get("ORDER_JAR", str(root / "src/order/target/order-service-0.1.0-SNAPSHOT.jar")))
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
log_path = root / "build" / ("windows" if sys.platform == "win32" else "wsl") / "order-smoke.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
with log_path.open("w", encoding="utf-8") as log:
    process = subprocess.Popen(["java", "-jar", str(jar), f"--server.port={port}",
                                "--server.address=127.0.0.1"], stdout=log, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 40
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"Order process exited: see {log_path}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health/live", timeout=1) as response:
                    assert response.status == 200
                    assert json.load(response)["status"] == "UP"
                break
            except (urllib.error.URLError, TimeoutError):
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Order startup timed out: see {log_path}")
                time.sleep(0.2)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=2)
            raise AssertionError("Skeleton incorrectly reports business readiness")
        except urllib.error.HTTPError as response:
            assert response.code == 503
            assert json.load(response)["ready"] is False
        result = {"platform": sys.platform, "live": 200, "ready": 503, "businessReady": False, "packagedJarStarted": True}
        report_dir = root / "tests/reports" / ("windows" if sys.platform == "win32" else "wsl")
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "s0-order-smoke.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
