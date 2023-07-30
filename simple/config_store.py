from dataclasses import dataclass, field
from mppi import MPPIConfig
from isaacgym_wrapper import IsaacGymConfig, ActorWrapper
from hydra.core.config_store import ConfigStore

from typing import List, Optional


@dataclass
class ExampleConfig:
    render: bool
    n_steps: int
    mppi: MPPIConfig
    isaacgym: IsaacGymConfig
    goal: List[float]
    nx: int
    actors: List[str]
    initial_actor_positions: List[List[float]]
    cfg_root: str


cs = ConfigStore.instance()
cs.store(name="config_panda_push", node=ExampleConfig)
cs.store(name="config_panda_c_space_goal", node=ExampleConfig)
cs.store(group="mppi", name="base_mppi", node=MPPIConfig)
cs.store(group="isaacgym", name="base_isaacgym", node=IsaacGymConfig)
