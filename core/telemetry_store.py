import os
import json
import redis.asyncio as redis
from typing import Optional, Any
from pydantic import BaseModel
from config import settings

class EnrichedContextMatrix(BaseModel):
    """Calculated metrics handed down to the optimization Tiers."""
    router_id: str
    timestamp: int
    is_wireless: bool
    calc_download_mbps: float
    calc_upload_mbps: float
    latency_ms: float
    packet_loss: float
    signal_dbm: int
    noise_dbm: int
    system_load: float
    total_flows: int

class RedisTelemetryStore:
    def __init__(self):
        # Initializes a connection pool pointing to your Redis instance.
        # Fetch environment variables safely
        redis_host = os.getenv("REDISHOST", os.getenv("REDISHOST", "redis.railway.internal"))
        raw_port = os.getenv("REDISPORT", os.getenv("REDISPORT", "6379"))
        redis_password= os.getenv("REDISPASSWORD","crAzOTGOyZIchveBAxtgjkioHMjbtvnD")
        redis_username= os.getenv("REDISUSER","default")

        # Strip spaces and fall back to 6379 if the string is empty
        if not raw_port or raw_port.strip() == "":
            redis_port = 6379
        else:
            redis_port = int(raw_port)

        # Fall back to localhost if the host string is empty
        if not redis_host or redis_host.strip() == "":
            redis_host = "localhost"

        self.client = redis.Redis(host=redis_host, port=redis_port,password=redis_password,username=redis_username, decode_responses=True)

    async def update_and_calculate_deltas(self, raw_telemetry: Any) -> EnrichedContextMatrix:
        """
        Ingests raw telemetry, evaluates delta variations against persistent records 
        inside Redis, and compiles the multi-tenant context matrix.
        """
        rid = raw_telemetry.router_id
        current_time = raw_telemetry.timestamp
        current_rx = raw_telemetry.interface.rx_bytes
        current_tx = raw_telemetry.interface.tx_bytes

        calc_down_mbps = 0.0
        calc_up_mbps = 0.0

        # Construct a unique Redis key for this router's historical byte limits
        redis_key = f"router:state:{rid}"

        # Fetch the previous historical state from Redis
        raw_prev_state = await self.client.get(redis_key)

        if raw_prev_state:
            prev_state = json.loads(raw_prev_state)
            
            # Compute time window variance delta (Δt)
            delta_time = float(current_time - prev_state["timestamp"])

            if delta_time > 0.01:
                delta_rx_bytes = max(0, current_rx - prev_state["rx_bytes"])
                delta_tx_bytes = max(0, current_tx - prev_state["tx_bytes"])

                # Mathematical translation: (Bytes -> Bits -> Megabits) / time delta
                calc_down_mbps = round(((delta_rx_bytes * 8) / 1_000_000.0) / delta_time, 3)
                calc_up_mbps = round(((delta_tx_bytes * 8) / 1_000_000.0) / delta_time, 3)

        # Build the new state snapshot payload
        new_state = {
            "timestamp": current_time,
            "rx_bytes": current_rx,
            "tx_bytes": current_tx
        }

        # Commit back to Redis with a 2-hour expiration safety window (7200 seconds).
        # If a router catches fire or goes offline permanently, its data clears automatically.
        await self.client.setex(redis_key, 7200, json.dumps(new_state))

        return EnrichedContextMatrix(
            router_id=rid,
            timestamp=raw_telemetry.timestamp,
            is_wireless=True if raw_telemetry.interface.type == "wireless" else False,
            calc_download_mbps=calc_down_mbps,
            calc_upload_mbps=calc_up_mbps,
            latency_ms=float(raw_telemetry.latency_profile.avg_latency_ms),
            packet_loss=float(raw_telemetry.latency_profile.packet_loss_percent),
            signal_dbm=int(raw_telemetry.wireless_profile.signal_strength_dbm),
            noise_dbm=int(raw_telemetry.wireless_profile.noise_floor_dbm),
            system_load=float(raw_telemetry.system_load),
            total_flows=int(raw_telemetry.active_flows.total_tracked)
        )

# Global tracking instance for ingestion layer dependency injection
import os
global_telemetry_store = RedisTelemetryStore()
