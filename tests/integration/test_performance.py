"""In-process resolution benchmark, excluding Python startup and child Git I/O."""

import os
import statistics
import time

from uv_shims.git.cli import resolve


def test_resolution_cpu_overhead_stays_below_five_milliseconds(
    isolated_env, temp_repo, monkeypatch, record_property
):
    isolated_env.write_config("""[[identities]]
id = "acme"
name = "Acme Bot"
email = "bot@acme.invalid"
match_patterns = ["github.com/acme/*"]
[identities.https]
token_env_var = "BOT_TOKEN"
""")
    repo = temp_repo(remotes={"origin": "https://github.com/acme/app.git"})
    monkeypatch.chdir(repo.path)
    environment = dict(os.environ, UV_SHIM_GIT_MODE="agent", BOT_TOKEN="benchmark-token")
    # push resolves the complete config/mode/repository/identity/credential plan,
    # without commit's external sequencer probe. Warm lazy imports and OS caches.
    argv = ["push", "origin", "main"]
    for _ in range(10):
        resolve(argv, environment)

    cpu_samples = []
    elapsed_samples = []
    for _ in range(7):
        elapsed_start = time.perf_counter()
        cpu_start = time.process_time()
        for _ in range(100):
            resolution = resolve(argv, environment)
        cpu_samples.append((time.process_time() - cpu_start) / 100)
        elapsed_samples.append((time.perf_counter() - elapsed_start) / 100)

    cpu_ms = statistics.median(cpu_samples) * 1000
    elapsed_ms = statistics.median(elapsed_samples) * 1000
    record_property("resolution_cpu_ms", cpu_ms)
    record_property("resolution_elapsed_ms", elapsed_ms)
    print(f"resolution: median CPU {cpu_ms:.3f} ms; elapsed {elapsed_ms:.3f} ms")
    assert resolution.plan.matched_identity.id == "acme"
    assert resolution.plan.is_write and not resolution.plan.fail_closed
    assert cpu_ms < 5, f"median in-process CPU resolution cost was {cpu_ms:.3f} ms"
