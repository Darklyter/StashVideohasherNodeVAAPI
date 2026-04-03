# health_check.py

import os
import sys
import subprocess
from helpers.stash_utils import stash
import config

def check_stash_connection():
    """Verify Stash API is reachable"""
    try:
        # Simple API call to verify connection
        stash.find_scenes(filter={"per_page": 1}, fragment="id")
        return True, "Stash API connection successful"
    except Exception as e:
        return False, f"Stash API connection failed: {e}"

def check_phash_backend():
    """Verify the configured phash backend is ready"""
    if config.phash_backend == "binary":
        binary_path = config.binary
        if not os.path.exists(binary_path):
            return False, f"Binary not found: {binary_path}"
        if not os.access(binary_path, os.X_OK):
            return False, f"Binary not executable: {binary_path}"
        return True, f"Binary found: {binary_path}"
    else:
        try:
            import numpy
            import scipy
            return True, f"Python phash ready (numpy {numpy.__version__}, scipy {scipy.__version__})"
        except ImportError as e:
            return False, f"Missing dependency: {e} — run: pip install numpy scipy"

def check_ffmpeg_available():
    """Verify ffmpeg and ffprobe are available"""
    try:
        subprocess.run([config.ffmpeg, '-version'], capture_output=True, check=True, timeout=10)
        subprocess.run([config.ffprobe, '-version'], capture_output=True, check=True, timeout=10)
        return True, "FFmpeg and FFprobe available"
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return False, f"FFmpeg/FFprobe not available: {e}"

def check_output_paths():
    """Verify output paths are writable"""
    paths_to_check = []

    if config.generate_sprite:
        paths_to_check.append(("Sprite path", config.sprite_path))

    if config.generate_preview:
        paths_to_check.append(("Preview path", config.preview_path))

    for name, path in paths_to_check:
        if not os.path.exists(path):
            return False, f"{name} does not exist: {path}"
        if not os.access(path, os.W_OK):
            return False, f"{name} is not writable: {path}"

    return True, "All output paths are writable"

def check_vaapi_device(vaapi_device):
    """Verify VAAPI device is accessible if VAAPI is enabled"""
    if vaapi_device and not config.windows:
        if not os.path.exists(vaapi_device):
            return False, f"VAAPI device not found: {vaapi_device}"
        if not os.access(vaapi_device, os.R_OK | os.W_OK):
            return False, f"VAAPI device not accessible: {vaapi_device}"
        return True, f"VAAPI device accessible: {vaapi_device}"
    return True, "VAAPI check skipped (disabled or Windows)"

def check_vaapi_encoding(vaapi_device):
    """Test a real VAAPI encode using a synthetic source — verifies ffmpeg can use the GPU"""
    if config.windows:
        return True, "VAAPI encoding check skipped (Windows)"
    test_output = os.path.join(os.getcwd(), ".tmp", "vaapi_encode_test.mp4")
    try:
        os.makedirs(os.path.dirname(test_output), exist_ok=True)
        result = subprocess.run([
            config.ffmpeg,
            '-f', 'lavfi', '-i', 'testsrc=duration=1:size=128x72:rate=10',
            '-vaapi_device', vaapi_device,
            '-vf', 'format=nv12,hwupload,scale_vaapi=128:72',
            '-c:v', 'h264_vaapi',
            '-global_quality', '25',
            '-an', '-y', test_output
        ], capture_output=True, timeout=30)
        if result.returncode != 0:
            lines = result.stderr.decode('utf-8', errors='replace').strip().splitlines()
            error = lines[-1] if lines else "no error output"
            return False, f"VAAPI encode failed: {error}"
        if not os.path.exists(test_output) or os.path.getsize(test_output) == 0:
            return False, "VAAPI encode produced no output"
        return True, f"VAAPI encoding working on {vaapi_device}"
    except subprocess.TimeoutExpired:
        return False, "VAAPI encode test timed out"
    except Exception as e:
        return False, f"VAAPI encode test error: {e}"
    finally:
        if os.path.exists(test_output):
            os.remove(test_output)

def check_nvenc_encoding():
    """Test a real NVENC encode using a synthetic source — verifies ffmpeg can use the NVIDIA GPU"""
    test_output = os.path.join(os.getcwd(), ".tmp", "nvenc_encode_test.mp4")
    try:
        os.makedirs(os.path.dirname(test_output), exist_ok=True)
        result = subprocess.run([
            config.ffmpeg,
            '-f', 'lavfi', '-i', 'testsrc=duration=1:size=128x72:rate=10',
            '-c:v', 'h264_nvenc',
            '-cq:v', '25',
            '-preset', 'p4',
            '-an', '-y', test_output
        ], capture_output=True, timeout=30)
        if result.returncode != 0:
            lines = result.stderr.decode('utf-8', errors='replace').strip().splitlines()
            error = lines[-1] if lines else "no error output"
            return False, f"NVENC encode failed: {error}"
        if not os.path.exists(test_output) or os.path.getsize(test_output) == 0:
            return False, "NVENC encode produced no output"
        return True, "NVENC encoding working"
    except subprocess.TimeoutExpired:
        return False, "NVENC encode test timed out"
    except Exception as e:
        return False, f"NVENC encode test error: {e}"
    finally:
        if os.path.exists(test_output):
            os.remove(test_output)

def check_temp_directory():
    """Verify temp directory can be created"""
    try:
        temp_dir = os.path.join(os.getcwd(), ".tmp")
        os.makedirs(temp_dir, exist_ok=True)
        # Try to write a test file
        test_file = os.path.join(temp_dir, "health_check_test")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        return True, "Temp directory writable"
    except Exception as e:
        return False, f"Cannot write to temp directory: {e}"

def run_health_check(vaapi_device=None):
    """Run all health checks and return results"""
    checks = [
        ("Stash API Connection", check_stash_connection),
        ("PHash Backend", check_phash_backend),
        ("FFmpeg/FFprobe", check_ffmpeg_available),
        ("Output Paths", check_output_paths),
        ("Temp Directory", check_temp_directory),
    ]

    if vaapi_device:
        checks.append(("VAAPI Device", lambda: check_vaapi_device(vaapi_device)))
        checks.append(("VAAPI Encoding", lambda: check_vaapi_encoding(vaapi_device)))
    elif config.nvenc:
        checks.append(("NVENC Encoding", check_nvenc_encoding))

    results = []
    all_passed = True

    print("\n🏥 Running Health Checks...")
    print("=" * 60)

    for check_name, check_func in checks:
        try:
            passed, message = check_func()
            status = "✅" if passed else "❌"
            print(f"{status} {check_name}: {message}")
            results.append((check_name, passed, message))
            if not passed:
                all_passed = False
        except Exception as e:
            print(f"❌ {check_name}: Unexpected error - {e}")
            results.append((check_name, False, str(e)))
            all_passed = False

    print("=" * 60)

    if all_passed:
        print("✅ All health checks passed!\n")
    else:
        print("❌ Some health checks failed. Please resolve issues before processing.\n")

    return all_passed, results
