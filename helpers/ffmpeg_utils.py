# helpers/ffmpeg_utils.py
#
# Shared plumbing for every external process the hasher starts:
#   - run():            subprocess wrapper with a mandatory timeout, isolated from the
#                       terminal's Ctrl+C, and tracked so shutdown can stop it deliberately
#   - request_shutdown: flips the global shutdown flag and terminates running children
#   - atomic_output():  write to a temp name, rename into place only on success
#   - tmp_path():       per-process temp directory under <project>/.tmp
#   - h264_encode_args: the one place that decides VAAPI / NVENC / software encode options

import atexit
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import threading

import config

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_BASE = os.path.join(PROJECT_DIR, ".tmp")
_RUN_PREFIX = f"{socket.gethostname()}-"
_RUN_DIR = os.path.join(TMP_BASE, f"{_RUN_PREFIX}{os.getpid()}")

shutdown_event = threading.Event()


class ShutdownRequested(BaseException):
    """
    Raised inside worker threads once shutdown has been requested.

    Deliberately a BaseException: the many `except Exception` handlers that log a
    failure and tag the scene as an error must NOT see an interrupted job as a
    failed one. `finally` blocks (claim release, temp cleanup) still run.
    """


# ─────────────────────────────────────────────
# Process tracking / shutdown
# ─────────────────────────────────────────────
_procs = set()
_procs_lock = threading.Lock()
_semaphore = None
_semaphore_lock = threading.Lock()


def _get_semaphore():
    """Optional global cap on concurrent child processes (config.max_ffmpeg_procs, 0 = no cap)."""
    global _semaphore
    limit = getattr(config, "max_ffmpeg_procs", 0) or 0
    if limit <= 0:
        return None
    with _semaphore_lock:
        if _semaphore is None:
            _semaphore = threading.BoundedSemaphore(limit)
        return _semaphore


def _signal_proc(proc, kill=False):
    """Signal a child and everything it started (each child leads its own process group)."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL if kill else signal.SIGTERM)
        elif kill:
            proc.kill()
        else:
            proc.terminate()
    except Exception:
        pass


def _signal_all(kill=False):
    with _procs_lock:
        procs = list(_procs)
    for proc in procs:
        _signal_proc(proc, kill)


def request_shutdown():
    """Set the shutdown flag and stop every running child. Safe to call from a signal handler."""
    shutdown_event.set()

    def _stop():
        _signal_all(kill=False)
        # Anything still alive after a grace period gets SIGKILL
        if not _wait_for_children(3.0):
            _signal_all(kill=True)

    threading.Thread(target=_stop, daemon=True).start()


def kill_all():
    """Immediately SIGKILL every running child (used for a forced exit)."""
    _signal_all(kill=True)


def _wait_for_children(seconds):
    import time
    deadline = time.time() + seconds
    while time.time() < deadline:
        with _procs_lock:
            if not _procs:
                return True
        time.sleep(0.1)
    return False


def run(cmd, timeout, check=True):
    """
    Run an external command and return a CompletedProcess.

    - Children run in their own session/process group, so a Ctrl+C typed in the
      terminal reaches only the Python process; shutdown stops them deliberately.
    - A timeout is always required; on expiry the child is killed and
      subprocess.TimeoutExpired is raised.
    - Raises ShutdownRequested instead of an error when the run was cut short
      by shutdown.
    """
    if shutdown_event.is_set():
        raise ShutdownRequested()

    sem = _get_semaphore()
    if sem is not None:
        while not sem.acquire(timeout=0.5):
            if shutdown_event.is_set():
                raise ShutdownRequested()
    try:
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(cmd, **kwargs)
        with _procs_lock:
            _procs.add(proc)
        try:
            if shutdown_event.is_set():
                _signal_proc(proc)
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _signal_proc(proc, kill=True)
                proc.communicate()
                raise
        finally:
            with _procs_lock:
                _procs.discard(proc)
    finally:
        if sem is not None:
            sem.release()

    if proc.returncode != 0:
        if shutdown_event.is_set():
            raise ShutdownRequested()
        if check:
            raise subprocess.CalledProcessError(proc.returncode, cmd, out, err)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def error_detail(exc):
    """Short human-readable reason for a failed run() call."""
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"timed out after {exc.timeout:.0f}s"
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        lines = stderr.strip().splitlines()
        if lines:
            return lines[-1]
        if exc.returncode < 0:
            return f"killed by signal {-exc.returncode}"
        return f"exit status {exc.returncode}"
    return str(exc)


def probe_duration(video_path, timeout=60):
    """Return the container duration in seconds via ffprobe. Raises RuntimeError if unknown."""
    try:
        result = run(
            [config.ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Could not determine duration for {video_path}: ffprobe {error_detail(e)}")
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        stderr = result.stderr.decode('utf-8', errors='replace').strip()
        raise RuntimeError(f"Could not determine duration for {video_path}: {stderr}")


# ─────────────────────────────────────────────
# Encoder selection
# ─────────────────────────────────────────────
def h264_encode_args(use_vaapi, vaapi_device, width=640):
    """
    Return (input_options, output_options) for an H.264 encode scaled to `width`
    with the aspect ratio preserved (even height).

    input_options go before `-i`; output_options go after it.
    """
    if use_vaapi and vaapi_device:
        return (
            ['-vaapi_device', vaapi_device],
            ['-vf', f'format=nv12,hwupload,scale_vaapi=w={width}:h=-2',
             '-c:v', 'h264_vaapi', '-global_quality', '18'],
        )
    if config.nvenc:
        return (
            [],
            ['-vf', f'scale={width}:-2', '-c:v', 'h264_nvenc', '-cq:v', '18', '-preset', 'p4'],
        )
    return (
        [],
        ['-vf', f'scale={width}:-2', '-c:v', 'libx264', '-crf', '18', '-preset', 'slow'],
    )


# ─────────────────────────────────────────────
# Output and temp files
# ─────────────────────────────────────────────
@contextlib.contextmanager
def atomic_output(final_path):
    """
    Yield a temp path next to `final_path` (same extension, so ffmpeg picks the
    right muxer). On clean exit the temp file is renamed over `final_path`; on any
    error or interruption it is deleted, so a partial file never looks finished.
    """
    directory, name = os.path.split(final_path)
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, f".partial-{os.getpid()}-{threading.get_ident()}-{name}")
    try:
        yield tmp
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            raise RuntimeError(f"No output produced for {name}")
        os.replace(tmp, final_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def tmp_path(name):
    """Path for a temp file/dir inside this process's own temp directory."""
    os.makedirs(_RUN_DIR, exist_ok=True)
    return os.path.join(_RUN_DIR, name)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except Exception:
        return True
    return True


def clean_tmp(final=False):
    """
    Remove this process's temp directory, plus directories left behind by dead
    processes on this host. Other live instances (or other hosts sharing the
    project directory) are left alone. With final=True, .tmp itself is removed
    when nothing else is using it.
    """
    shutil.rmtree(_RUN_DIR, ignore_errors=True)
    try:
        entries = os.listdir(TMP_BASE)
    except OSError:
        entries = []
    for entry in entries:
        if not entry.startswith(_RUN_PREFIX):
            continue
        pid_text = entry[len(_RUN_PREFIX):]
        if pid_text.isdigit() and os.name == "posix" and not _pid_alive(int(pid_text)):
            shutil.rmtree(os.path.join(TMP_BASE, entry), ignore_errors=True)
    if final:
        try:
            os.rmdir(TMP_BASE)  # only succeeds when empty
        except OSError:
            pass


# Never leave this process's temp directory behind, whatever the exit path
atexit.register(clean_tmp, final=True)
