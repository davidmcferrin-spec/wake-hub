"""Electrical samples. The poller is best-effort and never raises into the API."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from wakehub.hub import Hub
from wakehub.inventory import utcnow

log = logging.getLogger("wakehub.metrics")


def record(hub: Hub, source_kind: str, source_id: int, device_id: int | None, samples: list[tuple[str, float, str]]) -> None:
    now = utcnow()
    hub.write_many(
        [
            (
                """
                INSERT INTO metric_samples (recorded_at, source_kind, source_id, device_id, metric, value, unit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (now, source_kind, source_id, device_id, metric, float(value), unit),
            )
            for metric, value, unit in samples
            if value is not None
        ]
    )


def query_metrics(
    hub: Hub,
    *,
    source_kind: str | None = None,
    source_id: int | None = None,
    device_id: int | None = None,
    metric: str | None = None,
    limit: int = 400,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if source_kind:
        clauses.append("source_kind = ?")
        params.append(source_kind)
    if source_id is not None:
        clauses.append("source_id = ?")
        params.append(source_id)
    if device_id is not None:
        clauses.append("device_id = ?")
        params.append(device_id)
    if metric:
        clauses.append("metric = ?")
        params.append(metric)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 2000)))
    rows = hub.query(
        f"SELECT * FROM metric_samples {where} ORDER BY id DESC LIMIT ?",
        tuple(params),
    )
    return [
        {
            "recorded_at": row["recorded_at"],
            "source_kind": row["source_kind"],
            "source_id": row["source_id"],
            "device_id": row["device_id"],
            "metric": row["metric"],
            "value": row["value"],
            "unit": row["unit"],
        }
        for row in rows
    ]


def device_metrics(hub: Hub, device_id: int, limit: int = 400) -> list[dict[str, Any]]:
    from wakehub.inventory import get_device

    device = get_device(hub, device_id)
    rows = query_metrics(hub, device_id=device_id, limit=limit)
    for method in device["methods"]:
        if method["kind"] == "pdu":
            rows.extend(query_metrics(hub, source_kind="pdu", source_id=method["pdu_id"], limit=limit))
        elif method["kind"] == "plug":
            rows.extend(query_metrics(hub, source_kind="plug", source_id=method["plug_id"], limit=limit))
        elif method["kind"] == "ups":
            rows.extend(query_metrics(hub, source_kind="ups", source_id=method["ups_id"], limit=limit))
        elif method["kind"] == "jetkvm":
            rows.extend(query_metrics(hub, source_kind="jetkvm", source_id=method["jetkvm_id"], limit=limit))
    rows.sort(key=lambda item: item["recorded_at"], reverse=True)
    return rows[:limit]


def power_snapshot(hub: Hub, device: dict[str, Any]) -> dict[str, Any]:
    """One metered source per device. A plug beats DC, which beats a PDU bank, which beats the UPS load."""
    empty = {
        "metered": False,
        "source": None,
        "watts": None,
        "current_a": None,
        "energy_wh": None,
        "recorded_at": None,
        "history": [],
        "message": "No metered source is linked to this device.",
    }
    for kind in ("plug", "jetkvm", "pdu", "ups"):
        method = next((item for item in device.get("methods") or [] if item.get("kind") == kind), None)
        if method is None:
            continue
        reading = _source_reading(hub, kind, method)
        if reading is not None:
            return reading
    return empty


def _source_reading(hub: Hub, kind: str, method: dict[str, Any]) -> dict[str, Any] | None:
    if kind == "plug":
        name = _endpoint_name(hub, "plugs", method["plug_id"])
        return _pack(hub, "plug", method["plug_id"], "Smart plug", name, f"Smart plug {name}")
    if kind == "jetkvm":
        row = hub.query_one("SELECT name, extension FROM jetkvm_endpoints WHERE id = ?", (method["jetkvm_id"],))
        if row is None or row["extension"] != "dc-power":
            return None
        return _pack(hub, "jetkvm", method["jetkvm_id"], "JetKVM DC", row["name"], f"JetKVM {row['name']} DC")
    if kind == "pdu":
        name = _endpoint_name(hub, "pdus", method["pdu_id"])
        outlet = method.get("outlet")
        label = f"PDU {name} bank current" if outlet is None else f"PDU {name} outlet {outlet} (bank current)"
        return _pack(hub, "pdu", method["pdu_id"], "PDU bank", name, label)
    if kind == "ups":
        name = _endpoint_name(hub, "ups_cards", method["ups_id"])
        return _pack(hub, "ups", method["ups_id"], "UPS load", name, f"UPS {name} load")
    return None


def _endpoint_name(hub: Hub, table: str, item_id: int) -> str:
    row = hub.query_one(f"SELECT name FROM {table} WHERE id = ?", (item_id,))
    return row["name"] if row else str(item_id)


def _pack(hub: Hub, kind: str, source_id: int, source_kind_label: str, name: str, label: str) -> dict[str, Any]:
    history = _history(hub, kind, source_id)
    latest = history[-1] if history else {}
    reported = bool(history)
    return {
        "metered": True,
        "source": {"kind": kind, "id": source_id, "name": name, "label": label, "kind_label": source_kind_label},
        "watts": latest.get("watts"),
        "current_a": latest.get("current_a"),
        "energy_wh": latest.get("energy_wh"),
        "recorded_at": latest.get("recorded_at"),
        "history": history,
        "message": "" if reported else f"{label} has not reported yet.",
    }


def _history(hub: Hub, kind: str, source_id: int, limit: int = 24) -> list[dict[str, Any]]:
    rows = query_metrics(hub, source_kind=kind, source_id=source_id, limit=800)
    buckets: dict[str, dict[str, float]] = {}
    order: list[str] = []
    for row in rows:
        stamp = row["recorded_at"]
        if stamp not in buckets:
            if len(order) >= limit:
                continue
            order.append(stamp)
            buckets[stamp] = {}
        buckets[stamp][row["metric"]] = row["value"]
    points = []
    for stamp in reversed(order):
        bucket = buckets[stamp]
        points.append(
            {
                "recorded_at": stamp,
                "watts": _round(bucket.get("power_w")),
                "current_a": _round(_current(kind, bucket)),
                "energy_wh": _round(_energy(bucket)),
            }
        )
    return points


def _current(kind: str, bucket: dict[str, float]) -> float | None:
    if bucket.get("current_a") is not None:
        return bucket["current_a"]
    if kind != "pdu":
        return None
    banks = [value for key, value in bucket.items() if key.startswith("bank") and key.endswith("_amps")]
    if not banks:
        return None
    return sum(banks)


def _energy(bucket: dict[str, float]) -> float | None:
    if bucket.get("energy_wh") is not None:
        return bucket["energy_wh"]
    if bucket.get("energy_kwh") is not None:
        return bucket["energy_kwh"] * 1000
    return None


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def collect_once(hub: Hub) -> int:
    written = 0
    written += _collect_pdus(hub)
    written += _collect_plugs(hub)
    written += _collect_ups(hub)
    written += _collect_jetkvm(hub)
    _purge(hub)
    return written


def _collect_pdus(hub: Hub) -> int:
    from wakehub.endpoints import list_pdus, pdu_client

    count = 0
    for pdu in list_pdus(hub):
        try:
            _row, client = pdu_client(hub, pdu["id"])
            try:
                status = client.status()
            finally:
                client.close()
        except Exception as exc:
            log.info("pdu %s metrics skipped: %s", pdu["id"], exc)
            continue
        samples = [(f"bank{index}_amps", amps, "A") for index, amps in enumerate(status.bank_amps, start=1)]
        if status.temperature_c is not None:
            samples.append(("temperature_c", status.temperature_c, "C"))
        record(hub, "pdu", pdu["id"], None, samples)
        count += len(samples)
    return count


def _collect_plugs(hub: Hub) -> int:
    from wakehub.endpoints import list_plugs, plug_client

    count = 0
    for plug in list_plugs(hub):
        try:
            _row, client = plug_client(hub, plug["id"])
            status = client.status()
        except Exception as exc:
            log.info("plug %s metrics skipped: %s", plug["id"], exc)
            continue
        samples = []
        for metric, unit in (("power_w", "W"), ("voltage_v", "V"), ("current_a", "A"), ("energy_wh", "Wh"), ("energy_kwh", "kWh")):
            if status.get(metric) is not None:
                samples.append((metric, status[metric], unit))
        record(hub, "plug", plug["id"], plug.get("device_id"), samples)
        count += len(samples)
    return count


def _collect_ups(hub: Hub) -> int:
    from wakehub.endpoints import list_ups, ups_client

    count = 0
    for card in list_ups(hub):
        try:
            _row, client = ups_client(hub, card["id"])
            status = client.status()
        except Exception as exc:
            log.info("ups %s metrics skipped: %s", card["id"], exc)
            continue
        samples = []
        for metric, unit in (
            ("load_pct", "%"),
            ("capacity_pct", "%"),
            ("runtime_s", "s"),
            ("input_voltage_v", "V"),
            ("output_voltage_v", "V"),
            ("current_a", "A"),
            ("power_w", "W"),
        ):
            if status.get(metric) is not None:
                samples.append((metric, status[metric], unit))
        record(hub, "ups", card["id"], card.get("device_id"), samples)
        count += len(samples)
    return count


def _collect_jetkvm(hub: Hub) -> int:
    from wakehub.power import jetkvm_status

    # A poll opens a WebRTC session. JetKVM keeps one session, so this stays off unless the
    # device is a DC extension and the operator turned polling on for that endpoint.
    count = 0
    for item in hub.query(
        "SELECT id, device_id FROM jetkvm_endpoints WHERE poll_metrics = 1 AND extension = 'dc-power'"
    ):
        try:
            status = jetkvm_status(hub, item["id"])
        except Exception as exc:
            log.info("jetkvm %s metrics skipped: %s", item["id"], exc)
            continue
        dc = status.get("dc") or {}
        samples = []
        for metric, unit in (("voltage_v", "V"), ("current_a", "A"), ("power_w", "W")):
            if dc.get(metric) is not None:
                samples.append((metric, dc[metric], unit))
        if samples:
            record(hub, "jetkvm", item["id"], item["device_id"], samples)
            count += len(samples)
    return count


def _purge(hub: Hub) -> None:
    from wakehub.inventory import public_settings

    days = public_settings(hub)["metrics_retention_days"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    hub.write("DELETE FROM metric_samples WHERE recorded_at < ?", (cutoff,))


def start_poller(hub: Hub) -> threading.Event:
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                collect_once(hub)
            except Exception:
                log.exception("metric collection failed")
            from wakehub.inventory import public_settings

            stop.wait(public_settings(hub)["metrics_poll_seconds"])

    threading.Thread(target=loop, name="wakehub-metrics", daemon=True).start()
    return stop
