<h1 align="center">waitfor</h1>

<p align="center">
  <b>Block until a port, URL, file or command is ready. Then stop blocking.</b>
</p>

<p align="center">
  <a href="https://github.com/Viltrumlik/waitfor/actions/workflows/ci.yml"><img src="https://github.com/Viltrumlik/waitfor/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/dependencies-0-brightgreen" alt="Zero dependencies">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT"></a>
</p>

Every pipeline eventually grows a `sleep 10` before the tests, because the database was not up yet. Sleep is either too short — and the build is flaky — or too long, and you pay for it on every run, forever.

```bash
waitfor :5432 :6379 http://localhost:8000/health --timeout 60
```

Waits for all of them, returns the moment the last one answers, and fails loudly instead of letting the tests run against nothing.

## Targets

It works out what you mean:

| You write | It waits for |
|---|---|
| `5432` or `:5432` | TCP connect on `127.0.0.1:5432` |
| `db:5432` | TCP connect on that host |
| `http://…` `https://…` | an HTTP response in the 200–399 range |
| anything else | that path to exist |
| `--cmd "pg_isready"` | the command to exit `0` |

```bash
waitfor ./build/output.bin --timeout 300
waitfor --cmd "docker compose exec -T db pg_isready" --cmd "redis-cli ping"
waitfor http://localhost:8000/admin --status 401   # alive, just unauthorised
```

By default any `2xx` or `3xx` counts as alive. `--status` pins an exact code — useful when the thing you can reach without credentials is a `401`.

## Options

| | |
|---|---|
| `--timeout N` | give up after N seconds (default 30) |
| `--interval N` | seconds between attempts (default 0.5) |
| `--status CODE` | require this exact HTTP status |
| `-q, --quiet` | no progress, just the exit code |

Exit codes: `0` ready · `1` error · `2` usage · `3` timed out.

Progress goes to stderr, so piping stdout stays clean.

## In CI

```yaml
- run: docker compose up -d
- run: pipx install git+https://github.com/Viltrumlik/waitfor
- run: waitfor :5432 :6379 --timeout 90
- run: pytest
```

The build now fails with `timed out after 90s: 127.0.0.1:5432` instead of a hundred confusing connection errors from the test suite.

## Install

```bash
pipx install git+https://github.com/Viltrumlik/waitfor
```

Or take the file — one script, no dependencies:

```bash
curl -O https://raw.githubusercontent.com/Viltrumlik/waitfor/main/waitfor.py
python3 waitfor.py :5432
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

The tests bind real sockets, run a real HTTP server and create real files — nothing about readiness is mocked. CI runs on Ubuntu, macOS and Windows with Python 3.9 through 3.13.

## License

[MIT](LICENSE) © Alisher Muhammadaliyev ([@Viltrumlik](https://github.com/Viltrumlik))
