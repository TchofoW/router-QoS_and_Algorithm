import numpy as np
from config import settings
from core.telemetry_store import EnrichedContextMatrix

class Tier2FuzzyController:
    @staticmethod
    def _tri_membership(x: float, a: float, b: float, c: float) -> float:
        """Standard Triangular Membership Function."""
        if x <= a or x >= c:
            return 0.0
        if a < x <= b:
            return (x - a) / (b - a)
        if b < x < c:
            return (c - x) / (c - b)
        return 0.0

    @staticmethod
    def _trap_membership(x: float, a: float, b: float, c: float, d: float) -> float:
        """Standard Trapezoidal Membership Function."""
        if x <= a or x >= d:
            return 0.0
        if b <= x <= c:
            return 1.0
        if a < x < b:
            return (x - a) / (b - a)
        if c < x < d:
            return (d - x) / (d - c)
        return 0.0

    @classmethod
    def evaluate_link_scalar(cls, matrix: EnrichedContextMatrix) -> float:
        """
        Ingests the telemetry metrics and maps them through overlapping sets.
        Returns a link capacity scalar factor (alpha) between 0.1 and 1.0.
        """
        # If the interface is wired, skip wireless logic and evaluate wired congestion
        if not matrix.is_wireless:
            return cls._evaluate_wired_congestion(matrix.latency_ms)

        # -----------------------------------------------------------------
        # FUZZIFICATION LAYER: Input Membership Mappings
        # -----------------------------------------------------------------
        # Input 1: Wireless Signal Strength (RSSI)
        sig = matrix.signal_dbm
        sig_poor = cls._trap_membership(sig, -110, -110, -85, -75)
        sig_fair = cls._tri_membership(sig, -80, -70, -60)
        sig_good = cls._trap_membership(sig, -65, -55, 0, 0)

        # Input 2: Link Jitter / Current Latency Performance
        lat = matrix.latency_ms
        lat_low = cls._trap_membership(lat, 0, 0, 25, 45)
        lat_med = cls._tri_membership(lat, 35, 60, 90)
        lat_high = cls._trap_membership(lat, 75, 120, 5000, 5000)

        # -----------------------------------------------------------------
        # RULE INFERENCE LAYER (Mamdani-Style Matrix)
        # -----------------------------------------------------------------
        # We deduce three output singleton linguistic performance categories:
        # Severe Degradation (Scale down to 0.4), Moderate (0.75), Optimal (1.0)
        out_severe = max(sig_poor, lat_high)
        out_moderate = max(min(sig_fair, lat_med), min(sig_good, lat_med))
        out_optimal = min(sig_good, lat_low)

        # Ensure we have a safety baseline to prevent a division-by-zero anomaly
        total_weight = out_severe + out_moderate + out_optimal
        if total_weight == 0:
            return 1.0

        # -----------------------------------------------------------------
        # DEFUZZIFICATION LAYER (Sugeno Center-of-Gravity Fast Approximation)
        # -----------------------------------------------------------------
        # Combine weights against our crisp output categories to find alpha (α)
        alpha = ((out_severe * 0.4) + (out_moderate * 0.75) + (out_optimal * 1.0)) / total_weight
        return round(float(alpha), 3)

    @classmethod
    def _evaluate_wired_congestion(cls, latency_ms: float) -> float:
        """Simplified fuzzy scaling for fixed lines experiencing bufferbloat."""
        bloat = cls._trap_membership(latency_ms, 30, 70, 200, 500)
        # Invert bloat: 0% bloat = 1.0 scalar, 100% bloat = 0.5 safe clamp
        return round(1.0 - (bloat * 0.5), 3)
