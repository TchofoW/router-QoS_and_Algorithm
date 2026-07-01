from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional,Dict,Any
from typing import Optional
from config import settings
from core.telemetry_store import global_telemetry_store, EnrichedContextMatrix
from core.pipeline import ExecutionPipeline

# Initialize the Sovereign Brain core REST API engine
app = FastAPI(
    title="Sovereign Brain API Core",
    description="High-Performance Tiered Control Plane for OpenWrt Routers",
    version="1.0.0"
)

# =====================================================================
# PYDANTIC INBOUND SCHEMA VALIDATION SCHEMES
# =====================================================================

class InterfaceMetrics(BaseModel):
    name: str
    type: str
    rx_bytes: int
    tx_bytes: int
    rx_packets: int
    tx_packets: int
    rx_errors: int
    tx_errors: int

class WirelessProfile(BaseModel):
    signal_strength_dbm: int
    noise_floor_dbm: int
    tx_bitrate_mbps: float
    rx_bitrate_mbps: float
    expected_throughput_mbps: float

class LatencyProfile(BaseModel):
    ping_target: str
    avg_latency_ms: float
    packet_loss_percent: float

class ActiveFlows(BaseModel):
    total_tracked: int
    tcp_established: int

class RouterTelemetryPayload(BaseModel):
    """The master validation layout matching the OpenWrt shell client schema."""
    router_id: str = Field(..., description="The unique alpha-numeric MAC key of the active link interface")
    timestamp: int
    uptime_seconds: int
    system_load: str
    interface: InterfaceMetrics
    wireless_profile: WirelessProfile
    latency_profile: LatencyProfile
    active_flows: ActiveFlows

class QoSCommandPacket(BaseModel):
    """The outbound command packet returned synchronously to the router client."""
    qos_enabled: str
    download_limit: str
    upload_limit: str
    qdisc_algo: str

# =====================================================================
# API ENDPOINT DEFINITIONS
# =====================================================================

@app.get("/health")
async def health_check():
    """Simple endpoint to verify server responsiveness."""
    return {"status": "online", "monitored_nodes_active": len(global_telemetry_store._memory)}

@app.post("/api/telemetry", response_model=QoSCommandPacket)
async def ingest_router_telemetry(payload: RouterTelemetryPayload):
    """
    Ingests raw structural metrics from any authorized OpenWrt router, 
    calculates usage deltas, and orchestrates execution across optimization tiers.
    """
    try:
        # Step 1: Pass data through the state engine to calculate active Mbps speed
        print("Debug: Raw incoming payload")
        print(payload)
        context_matrix: EnrichedContextMatrix = await global_telemetry_store.update_and_calculate_deltas(payload)
        
        # Server console monitoring log
        print(f"[Node: {context_matrix.router_id}] Calculated Throughput -> "
              f"Down: {context_matrix.calc_download_mbps} Mbps | Up: {context_matrix.calc_upload_mbps} Mbps")

        # Step 2: Feed the matrix directly into the tiered pipeline loop (Tiers 1, 2, & 3 Evaluation)
        target_commands = await ExecutionPipeline.process(context_matrix)
        
        # Step 3: Package finalized commands and deliver them back down to the router client
        return QoSCommandPacket(
            qos_enabled=target_commands["qos_enabled"],
            download_limit=target_commands["download_limit"],
            upload_limit=target_commands["upload_limit"],
            qdisc_algo=target_commands["qdisc_algo"]
       # return {"status":"debug_mode_payload_received"}
    
        )

    except Exception as e:
        import traceback
        print("----CRITICAL SERVER ERROR!!--")
        traceback.print_exc()
        print("-------------------------------")
        # Prevent server crashes on corrupted telemetry arrays; log and return an HTTP Error code
        raise HTTPException(status_code=500, detail=f"Sovereign Ingestion Runtime Error: {str(e)}")
