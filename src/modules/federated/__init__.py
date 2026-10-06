"""
Federated learning package for privacy-preserving multi-node edge coordination.
"""

from src.modules.federated.model import EdgeMultimodalModel
from src.modules.federated.node import FederatedEdgeNode
from src.modules.federated.aggregator import FederatedAggregator, AggregationStrategy
from src.modules.federated.federated_engine import FederatedSimulationEngine

__all__ = [
    "EdgeMultimodalModel",
    "FederatedEdgeNode",
    "FederatedAggregator",
    "AggregationStrategy",
    "FederatedSimulationEngine",
]
