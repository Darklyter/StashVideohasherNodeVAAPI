import glob
import subprocess

def vaapi_available():
    """Check if VAAPI is available on the system."""
    # Render nodes first (renderD128, renderD129, ... — one per GPU), then legacy card nodes
    device_paths = sorted(glob.glob("/dev/dri/renderD*")) + sorted(glob.glob("/dev/dri/card*"))
    for device in device_paths:
        try:
            result = subprocess.run(
                ["vainfo", "--display", "drm", "--device", device],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=5
            )
            output = result.stdout.decode("utf-8")
            if "VA-API version" in output and "Driver version" in output:
                return True, device
        except Exception:
            continue
    return False, None
