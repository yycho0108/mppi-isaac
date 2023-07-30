import gym
import numpy as np
from urdfenvs.robots.generic_urdf.generic_diff_drive_robot import GenericDiffDriveRobot
from urdfenvs.urdf_common.urdf_env import UrdfEnv
from mppiisaac.planner.mppi_isaac import MPPIisaacPlanner
import hydra
import yaml
import mppiisaac
from yaml import SafeLoader
from omegaconf import OmegaConf
import os
import torch
from mpscenes.goals.static_sub_goal import StaticSubGoal

from mppiisaac.utils.config_store import ExampleConfig

urdf_file = (
    os.path.dirname(os.path.abspath(__file__))
    + "/../assets/urdf/jackal/jackal.urdf"
)

# MPPI to navigate a simple robot to a goal position

class Objective(object):
    def __init__(self, cfg, device):
        self.nav_goal = torch.tensor(cfg.goal, device=cfg.mppi.device)

    def compute_cost(self, sim):
        pos = torch.cat((sim.root_state[:, 0, 0:2], sim.root_state[:, 1, 0:2]), axis=1)
        cost = torch.clamp(
            torch.linalg.norm(pos - self.nav_goal, axis=1) - 0.05, min=0, max=1999
        )
        return cost


def initalize_environment(cfg) -> UrdfEnv:
    """
    Initializes the simulation environment.

    Adds an obstacle and goal visualizaion to the environment and
    steps the simulation once.

    Params
    ----------
    render
        Boolean toggle to set rendering on (True) or off (False).
    """
    # urdf_file = os.path.dirname(os.path.abspath(__file__)) + "/../assets/urdf/" + cfg.urdf_file
    with open(f'{os.path.dirname(mppiisaac.__file__)}/../conf/actors/jackal.yaml') as f:
        jackal_cfg = yaml.load(f, Loader=SafeLoader)
    robots = [
        GenericDiffDriveRobot(
            urdf=urdf_file,
            mode="vel",
            actuated_wheels=[
                "rear_right_wheel",
                "rear_left_wheel",
                "front_right_wheel",
                "front_left_wheel",
            ],
            castor_wheels=[],
            wheel_radius = jackal_cfg['wheel_radius'],
            wheel_distance = jackal_cfg['wheel_base'],
        ),
        GenericDiffDriveRobot(
            urdf=urdf_file,
            mode="vel",
            actuated_wheels=[
                "rear_right_wheel",
                "rear_left_wheel",
                "front_right_wheel",
                "front_left_wheel",
            ],
            castor_wheels=[],
            wheel_radius = jackal_cfg['wheel_radius'],
            wheel_distance = jackal_cfg['wheel_base'],
        ),
    ]
    env: UrdfEnv = gym.make("urdf-env-v0", dt=0.02, robots=robots, render=cfg.render)
    # Set the initial position and velocity of the jackal robot
    env.reset(pos=np.array(cfg.initial_actor_positions))
    return env


def set_planner(cfg):
    """
    Initializes the mppi planner for jackal robot.

    Params
    ----------
    goal_position: np.ndarray
        The goal to the motion planning problem.
    """
    objective = Objective(cfg, cfg.mppi.device)
    planner = MPPIisaacPlanner(cfg, objective)

    return planner


@hydra.main(version_base=None, config_path="../conf", config_name="config_multi_jackal")
def run_jackal_robot(cfg: ExampleConfig):
    """
    Set the gym environment, the planner and run jackal robot example.
    The initial zero action step is needed to initialize the sensor in the
    urdf environment.

    Params
    ----------
    n_steps
        Total number of simulation steps.
    render
        Boolean toggle to set rendering on (True) or off (False).
    """
    # Note: Workaround to trigger the dataclasses __post_init__ method
    cfg = OmegaConf.to_object(cfg)


    env = initalize_environment(cfg)
    planner = set_planner(cfg)

    action = np.zeros(8)
    ob, *_ = env.step(action)
    
    
    for _ in range(cfg.n_steps):
        #Calculate action with the fabric planner, slice the states to drop Z-axis [3] information.

        #Todo fix joint with zero friction

        ob_robot0 = ob["robot_0"]
        ob_robot1 = ob["robot_1"]
        action = planner.compute_action(
            q=list(ob_robot0["joint_state"]["position"]) + list(ob_robot1["joint_state"]["position"]),
            qdot=list(ob_robot0["joint_state"]["velocity"]) + list(ob_robot1["joint_state"]["velocity"]),
        )
        (
            ob,
            *_,
        ) = env.step(action)
    return {}


if __name__ == "__main__":
    res = run_jackal_robot()
