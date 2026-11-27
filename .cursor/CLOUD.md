# Cloud environment

Python 3.12. Create a venv and `pip install -e ".[dev]"`.

Tests: `pytest -q --tb=line`. ICMP probes need `iputils-ping` on `PATH`.

The app listens on `PORT` (default 8765). Outside Docker, `WAKEHUB_CONFIG_DIR` and `WAKEHUB_DATA_DIR` default to `./config` and `./data`.

Do not commit `config/` or `data/`.
