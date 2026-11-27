"""REST routes for PDUs, AMT, JetKVM, plugs, UPS, scans and metrics."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from wakehub.api import require_bearer, request_source
from wakehub.endpoints import (
    add_amt,
    add_jetkvm,
    add_pdu,
    add_plug,
    add_ups,
    list_amt,
    list_jetkvm,
    list_pdus,
    list_plugs,
    list_ups,
    public_jetkvm,
    remove_amt,
    remove_jetkvm,
    remove_pdu,
    remove_plug,
    remove_ups,
    update_amt,
    update_jetkvm,
    update_pdu,
    update_plug,
    update_ups,
)
from wakehub.hub import get_hub
from wakehub.metrics import device_metrics, query_metrics
from wakehub.power import (
    amt_power,
    amt_state,
    jetkvm_power,
    jetkvm_status,
    list_pdu_outlets,
    plug_power,
    plug_status,
    set_pdu_outlet,
    ups_action,
    ups_status,
)
from wakehub.scan import add_from_scan, get_scan, list_scans, start_scan
from fastapi import Request


class PduIn(BaseModel):
    name: str
    host: str
    port: int = 80
    use_tls: bool = False
    username: str = "admin"
    password: str | None = None
    outlet_names: dict[str, str] | None = None


class PduPatch(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    use_tls: bool | None = None
    username: str | None = None
    password: str | None = None
    outlet_names: dict[str, str] | None = None


class OutletIn(BaseModel):
    action: str
    confirm: bool = False


class AmtIn(BaseModel):
    name: str
    host: str
    port: int | None = None
    use_tls: bool = False
    insecure_tls: bool = True
    username: str = "admin"
    password: str
    device_id: int | None = None


class AmtPatch(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    use_tls: bool | None = None
    insecure_tls: bool | None = None
    username: str | None = None
    password: str | None = None
    device_id: int | None = None


class JetIn(BaseModel):
    name: str
    host: str
    port: int | None = None
    use_tls: bool = False
    insecure_tls: bool = True
    password: str | None = None
    device_id: int | None = None


class JetPatch(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    use_tls: bool | None = None
    insecure_tls: bool | None = None
    password: str | None = None
    device_id: int | None = None


class JetPowerIn(BaseModel):
    action: str
    confirm: bool = False
    extension: str = "auto"


class PlugIn(BaseModel):
    name: str
    kind: str
    host: str
    port: int = 80
    username: str = ""
    password: str | None = None
    protocol: str = "auto"
    switch_id: int = 0
    device_id: int | None = None


class PlugPatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    protocol: str | None = None
    switch_id: int | None = None
    device_id: int | None = None


class PlugPowerIn(BaseModel):
    action: str
    confirm: bool = False
    cycle_seconds: float = 5


class UpsIn(BaseModel):
    name: str
    host: str
    port: int = 161
    snmp_version: str = "2c"
    community: str | None = None
    v3_user: str = ""
    v3_auth_proto: str = "sha"
    v3_auth: str | None = None
    v3_priv_proto: str = "aes"
    v3_priv: str | None = None
    device_id: int | None = None


class UpsPatch(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    snmp_version: str | None = None
    community: str | None = None
    v3_user: str | None = None
    v3_auth_proto: str | None = None
    v3_auth: str | None = None
    v3_priv_proto: str | None = None
    v3_priv: str | None = None
    device_id: int | None = None


class UpsActionIn(BaseModel):
    action: str
    confirm: bool = False
    delay_seconds: int | None = None
    outlet: int | None = None


class ScanIn(BaseModel):
    cidr: str | None = None


class AddFromScanIn(BaseModel):
    kind: str
    name: str | None = None
    password: str | None = None
    username: str | None = None
    community: str | None = None
    plug_kind: str | None = None


def control_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_bearer)])

    @router.get("/pdus", tags=["pdu"])
    def pdus() -> list[dict[str, Any]]:
        return list_pdus(get_hub())

    @router.post("/pdus", tags=["pdu"], status_code=201)
    def create_pdu(body: PduIn) -> dict[str, Any]:
        return add_pdu(get_hub(), body.model_dump())

    @router.patch("/pdus/{pdu_id}", tags=["pdu"])
    def patch_pdu(pdu_id: int, body: PduPatch) -> dict[str, Any]:
        return update_pdu(get_hub(), pdu_id, body.model_dump(exclude_unset=True))

    @router.delete("/pdus/{pdu_id}", tags=["pdu"], status_code=204)
    def delete_pdu(pdu_id: int):
        remove_pdu(get_hub(), pdu_id)
        from fastapi import Response

        return Response(status_code=204)

    @router.get("/pdus/{pdu_id}/outlets", tags=["pdu"])
    def outlets(pdu_id: int) -> dict[str, Any]:
        return list_pdu_outlets(get_hub(), pdu_id)

    @router.post("/pdus/{pdu_id}/outlets/{outlet}", tags=["pdu"])
    def outlet_power(pdu_id: int, outlet: int, body: OutletIn, request: Request) -> dict[str, Any]:
        return set_pdu_outlet(get_hub(), pdu_id, outlet, body.action, confirm=body.confirm, source=request_source(request))

    @router.get("/amt", tags=["amt"])
    def amts() -> list[dict[str, Any]]:
        return list_amt(get_hub())

    @router.post("/amt", tags=["amt"], status_code=201)
    def create_amt(body: AmtIn) -> dict[str, Any]:
        return add_amt(get_hub(), body.model_dump())

    @router.patch("/amt/{amt_id}", tags=["amt"])
    def patch_amt(amt_id: int, body: AmtPatch) -> dict[str, Any]:
        return update_amt(get_hub(), amt_id, body.model_dump(exclude_unset=True))

    @router.delete("/amt/{amt_id}", tags=["amt"], status_code=204)
    def delete_amt(amt_id: int):
        remove_amt(get_hub(), amt_id)
        from fastapi import Response

        return Response(status_code=204)

    @router.get("/amt/{amt_id}/power", tags=["amt"])
    def amt_power_state(amt_id: int) -> dict[str, Any]:
        return amt_state(get_hub(), amt_id)

    @router.get("/jetkvm", tags=["jetkvm"])
    def jetkvms() -> list[dict[str, Any]]:
        return list_jetkvm(get_hub())

    @router.post("/jetkvm", tags=["jetkvm"], status_code=201)
    def create_jet(body: JetIn) -> dict[str, Any]:
        return add_jetkvm(get_hub(), body.model_dump())

    @router.patch("/jetkvm/{jetkvm_id}", tags=["jetkvm"])
    def patch_jet(jetkvm_id: int, body: JetPatch) -> dict[str, Any]:
        return update_jetkvm(get_hub(), jetkvm_id, body.model_dump(exclude_unset=True))

    @router.delete("/jetkvm/{jetkvm_id}", tags=["jetkvm"], status_code=204)
    def delete_jet(jetkvm_id: int):
        remove_jetkvm(get_hub(), jetkvm_id)
        from fastapi import Response

        return Response(status_code=204)

    @router.get("/jetkvm/{jetkvm_id}/status", tags=["jetkvm"])
    def jet_status(jetkvm_id: int) -> dict[str, Any]:
        return jetkvm_status(get_hub(), jetkvm_id)

    @router.post("/jetkvm/{jetkvm_id}/power", tags=["jetkvm"])
    def jet_power(jetkvm_id: int, body: JetPowerIn, request: Request) -> dict[str, Any]:
        return jetkvm_power(
            get_hub(),
            jetkvm_id,
            body.action,
            confirm=body.confirm,
            source=request_source(request),
            extension=body.extension,
        )

    @router.get("/jetkvm/{jetkvm_id}/console", tags=["jetkvm"])
    def jet_console(jetkvm_id: int) -> dict[str, Any]:
        from wakehub.endpoints import _row

        row = _row(get_hub(), "jetkvm", jetkvm_id)
        public = public_jetkvm(row)
        return {"url": public["console_url"], "jetkvm_id": jetkvm_id}

    @router.get("/plugs", tags=["plugs"])
    def plugs() -> list[dict[str, Any]]:
        return list_plugs(get_hub())

    @router.post("/plugs", tags=["plugs"], status_code=201)
    def create_plug(body: PlugIn) -> dict[str, Any]:
        return add_plug(get_hub(), body.model_dump())

    @router.patch("/plugs/{plug_id}", tags=["plugs"])
    def patch_plug(plug_id: int, body: PlugPatch) -> dict[str, Any]:
        return update_plug(get_hub(), plug_id, body.model_dump(exclude_unset=True))

    @router.delete("/plugs/{plug_id}", tags=["plugs"], status_code=204)
    def delete_plug(plug_id: int):
        remove_plug(get_hub(), plug_id)
        from fastapi import Response

        return Response(status_code=204)

    @router.get("/plugs/{plug_id}/status", tags=["plugs"])
    def one_plug(plug_id: int) -> dict[str, Any]:
        return plug_status(get_hub(), plug_id)

    @router.post("/plugs/{plug_id}/power", tags=["plugs"])
    def plug_switch(plug_id: int, body: PlugPowerIn, request: Request) -> dict[str, Any]:
        return plug_power(
            get_hub(),
            plug_id,
            body.action,
            confirm=body.confirm,
            source=request_source(request),
            cycle_seconds=body.cycle_seconds,
        )

    @router.get("/ups", tags=["ups"])
    def ups_list() -> list[dict[str, Any]]:
        return list_ups(get_hub())

    @router.post("/ups", tags=["ups"], status_code=201)
    def create_ups(body: UpsIn) -> dict[str, Any]:
        return add_ups(get_hub(), body.model_dump())

    @router.patch("/ups/{ups_id}", tags=["ups"])
    def patch_ups(ups_id: int, body: UpsPatch) -> dict[str, Any]:
        return update_ups(get_hub(), ups_id, body.model_dump(exclude_unset=True))

    @router.delete("/ups/{ups_id}", tags=["ups"], status_code=204)
    def delete_ups(ups_id: int):
        remove_ups(get_hub(), ups_id)
        from fastapi import Response

        return Response(status_code=204)

    @router.get("/ups/{ups_id}/status", tags=["ups"])
    def one_ups(ups_id: int) -> dict[str, Any]:
        return ups_status(get_hub(), ups_id)

    @router.post("/ups/{ups_id}/action", tags=["ups"])
    def one_ups_action(ups_id: int, body: UpsActionIn, request: Request) -> dict[str, Any]:
        return ups_action(
            get_hub(),
            ups_id,
            body.action,
            confirm=body.confirm,
            source=request_source(request),
            delay_seconds=body.delay_seconds,
            outlet=body.outlet,
        )

    @router.post("/scans", tags=["scan"], status_code=202)
    def create_scan(body: ScanIn) -> dict[str, Any]:
        return start_scan(get_hub(), body.cidr)

    @router.get("/scans", tags=["scan"])
    def scans() -> list[dict[str, Any]]:
        return list_scans(get_hub())

    @router.get("/scans/{scan_id}", tags=["scan"])
    def scan(scan_id: int) -> dict[str, Any]:
        return get_scan(get_hub(), scan_id)

    @router.post("/scans/{scan_id}/hosts/{host_id}/add", tags=["scan"], status_code=201)
    def adopt(scan_id: int, host_id: int, body: AddFromScanIn) -> dict[str, Any]:
        return add_from_scan(get_hub(), scan_id, host_id, body.kind, body.model_dump(exclude={"kind"}, exclude_none=True))

    @router.get("/metrics", tags=["metrics"])
    def metrics(
        source_kind: str | None = None,
        source_id: int | None = None,
        device_id: int | None = None,
        metric: str | None = None,
        limit: int = Query(default=400, ge=1, le=2000),
    ) -> list[dict[str, Any]]:
        return query_metrics(get_hub(), source_kind=source_kind, source_id=source_id, device_id=device_id, metric=metric, limit=limit)

    @router.get("/devices/{device_id}/metrics", tags=["metrics"])
    def one_device_metrics(device_id: int, limit: int = Query(default=400, ge=1, le=2000)) -> list[dict[str, Any]]:
        return device_metrics(get_hub(), device_id, limit=limit)

    return router
