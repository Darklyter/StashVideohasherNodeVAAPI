import subprocess

def vaapi_available():
    """Check if VAAPI is available on the system."""
    # Try common VAAPI device paths
    device_paths = [
        "/dev/dri/renderD128",
        "/dev/dri/card0",
        "/dev/dri/card1"
    ]
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
