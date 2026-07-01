import os
import json
import numpy as np
import redis.asyncio as redis
from datetime import datetime
from typing import Tuple, Optional
from config import settings
from core.telemetry_store import EnrichedContextMatrix

class Tier3MLEngine:
    # Use the same Redis configuration parameters
    _redis_host = os.getenv("REDIS_HOST", "redis.railway.internal")
    _redis_password = os.getenv("REDISPASSWORD","crAzOTGOyZIchveBAxtgjkioHMjbtvnD")
    _redis_user= os.getenv("REDISUSER","default")
    
    # Safe parsing: read environment string, strip whitespace, fall back if empty
    _raw_port = os.getenv("REDIS_PORT", "6379")
    _redis_port = int(_raw_port) if _raw_port.strip() else 6379
    
    client = redis.Redis(host=_redis_host, port=_redis_port,password=_redis_password, username=_redis_user, decode_responses=True)
    
    actions = [0.80, 0.85, 0.90, 0.95, 1.00]

    @classmethod
    async def optimize_and_learn(cls, matrix: EnrichedContextMatrix, fuzzy_scalar: float) -> Tuple[float, str]:
        rid = matrix.router_id
        current_hour = datetime.fromtimestamp(matrix.timestamp).hour
        
        # Redis Key Definitions for isolated multi-tenant tracking
        q_table_key = f"router:ml:qtable:{rid}"
        history_key = f"router:ml:history:{rid}"

        # 1. Fetch or initialize the Q-Table for this device from Redis
        raw_q_table = await cls.client.get(q_table_key)
        if raw_q_table:
            q_table = np.array(json.loads(raw_q_table))
        else:
            q_table = np.zeros((24, len(cls.actions)))

        # 2. Fetch tracking references from the previous loop iteration
        raw_history = await cls.client.get(history_key)
        
        # 3. REWARD CALCULATION LOOP (Evaluate the last action taken)
        if raw_history:
            history = json.loads(raw_history)
            last_state = int(history["last_state"])
            last_action_idx = int(history["last_action_idx"])

            # Compute Reward value
            reward = -(matrix.latency_ms) - (matrix.packet_loss * 15.0) + (matrix.calc_download_mbps * 2.0)

            # Standard Q-learning Bellman Update Equation
            old_value = q_table[last_state, last_action_idx]
            next_max = np.max(q_table[current_hour])
            
            q_table[last_state, last_action_idx] = old_value + settings.LEARNING_RATE * (
                reward + settings.DISCOUNT_FACTOR * next_max - old_value
            )

        # 4. ACTION SELECTION POLICY (Epsilon-Greedy)
        if np.random.rand() < settings.EXPLORATION_RATE:
            action_idx = np.random.choice(len(cls.actions))
        else:
            action_idx = int(np.argmax(q_table[current_hour]))

        chosen_ml_multiplier = cls.actions[action_idx]

        # 5. COMMIT COMPREHENSIVE DATA BACK TO REDIS CORES
        new_history = {
            "last_state": current_hour,
            "last_action_idx": action_idx
        }
        
        await cls.client.set(q_table_key, json.dumps(q_table.tolist()))
        await cls.client.setex(history_key, 7200, json.dumps(new_history))

        # Classify ideal line handling flavor
        chosen_qdisc = "cake" if matrix.total_flows > 300 or matrix.is_wireless else "fq_codel"

        return chosen_ml_multiplier, chosen_qdisc

import os
