import gym
from mppiisaac.planner.isaacgym_wrapper import IsaacGymWrapper, ActorWrapper
import yaml
from yaml import SafeLoader
import mppiisaac
import numpy as np
import hydra
from omegaconf import OmegaConf
import torch
import zerorpc
from mppiisaac.utils.config_store import ExampleConfig
from isaacgym import gymapi
import time
from examples.boxer_push_client import Objective
import sys
import os
import io

def torch_to_bytes(t: torch.Tensor) -> bytes:
    buff = io.BytesIO()
    torch.save(t, buff)
    buff.seek(0)
    return buff.read()


def bytes_to_torch(b: bytes) -> torch.Tensor:
    buff = io.BytesIO(b)
    return torch.load(buff)

def reset_trial(sim, init_pos, init_vel):
    sim.stop_sim()
    sim.start_sim()
    set_viewer(sim)    
    sim.set_dof_state_tensor(torch.tensor([init_pos[0], init_vel[0], init_pos[1], init_vel[1], init_pos[2], init_vel[2]], device="cuda:0"))

def set_viewer(sim):
    sim.gym.viewer_camera_look_at(
        sim.viewer, None, gymapi.Vec3(1., 6.5, 4), gymapi.Vec3(1., 0, 0)        # CAMERA LOCATION, CAMERA POINT OF INTEREST
    )

@hydra.main(version_base=None, config_path="../conf", config_name="config_boxer_push")
def run_boxer_robot(cfg: ExampleConfig):
   # Note: Workaround to trigger the dataclasses __post_init__ method
    cfg = OmegaConf.to_object(cfg)

    actors=[]
    for actor_name in cfg.actors:
        with open(f'{os.path.dirname(mppiisaac.__file__)}/../conf/actors/{actor_name}.yaml') as f:
            actors.append(ActorWrapper(**yaml.load(f, Loader=SafeLoader)))


    sim = IsaacGymWrapper(
        cfg.isaacgym,
        init_positions=cfg.initial_actor_positions,
        actors=actors,
        num_envs=1,
        viewer=True,
    )

    # Manually add table + block and restart isaacgym
    obj_index = 0
                #  l      w     h     mu      m     x    y
    obj_set =  [[0.300, 0.500, 0.3,  0.300, 1.000, 2.00, 2.0],     # Crate
                [0.100, 0.100, 0.05, 0.300, 0.100, 2.00, 2.0],     # Baseline 1, pose 1
                [0.100, 0.100, 0.05, 0.300, 0.100, 0.40, 0.0],     # Baseline 1, pose 2
                [0.116, 0.116, 0.06, 0.637, 0.016, 0.35, 0.0],     # Baseline 2, A
                [0.168, 0.237, 0.05, 0.232, 0.615, 0.38, 0.0],     # Baseline 2, B
                [0.198, 0.198, 0.06, 0.198, 0.565, 0.40, 0.0],     # Baseline 2, C
                [0.166, 0.228, 0.08, 0.312, 0.587, 0.39, 0.0],     # Baseline 2, D
                [0.153, 0.462, 0.05, 0.181, 0.506, 0.37, 0.0]]    # Baseline 2, E
    
    obj_ = obj_set[obj_index][:]

    obst_1_dim = [0.6, 0.8, 0.108]
    obst_1_pos = [1, 1, obst_1_dim[-1]/2]

    obst_2_dim = [0.6, 0.8, 0.108]
    obst_2_pos = [-1, 1, obst_2_dim[-1]/2]
    goal_pos = [0. , 0.]
    additions = [
        {
            "type": "box",
            "name": "obj_to_push",
            "size": [obj_[0], obj_[1], obj_[2]],
            "init_pos": [obj_[5], obj_[6], obj_[2] / 2],
            "mass": obj_[4],
            "fixed": False,
            "handle": None,
            "color": [0.2, 0.2, 1.0],
            "friction": obj_[3],
            "noise_sigma_size": [0.005, 0.005, 0.0],
            "noise_percentage_friction": 0.3,
            "noise_percentage_mass": 0.3,
        },
        {
            "type": "box",
            "name": "obst_1",
            "size": obst_1_dim,
            "init_pos": obst_1_pos,
            "fixed": True,
            "color": [255 / 255, 120 / 255, 57 / 255],
            "handle": None,
        },
        {
            "type": "box",
            "name": "obst_2",
            "size": obst_2_dim,
            "init_pos": obst_2_pos,
            "fixed": True,
            "color": [255 / 255, 120 / 255, 57 / 255],
            "handle": None,
        },
        # Add goal, 
        {
            "type": "box",
            "name": "goal",
            "size": [obj_[0], obj_[1], obj_[2]],
            "init_pos": [goal_pos[0], goal_pos[1], -obj_[2]/2 + 0.005],
            "fixed": True,
            "color": [119 / 255, 221 / 255, 119 / 255],
            "handle": None,
            "collision": False,
        }
    ]

    sim.add_to_envs(additions)

    planner = zerorpc.Client()
    planner.connect("tcp://127.0.0.1:4242")
    print("Mppi server found!")

    planner.add_to_env(additions)
    
    set_viewer(sim)
    
    # Helpers
    count = 0
    client_helper = Objective(cfg, cfg.mppi.device)
    init_time = time.time()
    block_index = 1
    timeout = 120
    data_time = []
    data_err = []
    n_trials = 0 
    rt_factor_seq = []
    data_rt = []

    while n_trials < cfg.n_steps:
        t = time.time()
        # Reset state
        planner.reset_rollout_sim(
            torch_to_bytes(sim.dof_state[0]),
            torch_to_bytes(sim.root_state[0]),
            torch_to_bytes(sim.rigid_body_state[0]),
        )
        # sim.gym.clear_lines(sim.viewer)
        
        # Compute action
        action = bytes_to_torch(planner.command())
        if torch.any(torch.isnan(action)):
            print("nan action")
            action = torch.zeros_like(action)

        # Apply action
        #sim.set_dof_velocity_target_tensor(10*action)
        sim.apply_robot_cmd_velocity(torch.unsqueeze(action, axis=0))

        # Step simulator
        sim.step()

        # Monitoring
        # Evaluation metrics 
        # ------------------------------------------------------------------------
        if count > 10:
            block_pos = sim.root_state[:, block_index, :3]
            block_ort = sim.root_state[:, block_index, 3:7]

            Ex, Ey, Etheta = client_helper.compute_metrics(block_pos, block_ort)
            metric_1 = 1.5*(Ex+Ey)+0.01*Etheta
            # print("Metric Baxter", metric_1)
            print("Ex", Ex)
            print("Ey", Ey)
            # print("Angle", Etheta)
            # Ex < 0.025 and Ey < 0.01 and Etheta < 0.05
            # Ex < 0.05 and Ey < 0.025 and Etheta < 0.17
            if Ex < 0.05 and Ey < 0.05 and Etheta < 0.17: 
                print("Success")
                final_time = time.time()
                time_taken = final_time - init_time
                print("Time to completion", time_taken)
                #reset_trial(sim, init_pos, init_vel)
                
                init_time = time.time()
                count = 0
                data_rt.append(np.sum(rt_factor_seq) / len(rt_factor_seq))
                data_time.append(time_taken)
                data_err.append(np.float64(metric_1))
                n_trials += 1
                return{}

            rt_factor_seq.append(cfg.isaacgym.dt/(time.time() - t))
            print(f"FPS: {1/(time.time() - t)} RT-factor: {cfg.isaacgym.dt/(time.time() - t)}")
            
            count = 0
        else:
            count +=1
        
        if time.time() - init_time >= timeout:
            # reset_trial(sim, init_pos, init_vel)
            init_time = time.time()
            count = 0
            n_trials += 1

    if len(data_time) > 0: 
        print("Num. trials", n_trials)
        print("Success rate", len(data_time)/n_trials*100)
        print("Avg. Time", np.mean(np.array(data_time)*np.array(data_rt)))    
        print("Std. Time", np.std(np.array(data_time)*np.array(data_rt)))
    else:
        print("Seccess rate is 0")

    return {}

if __name__ == "__main__":
    res = run_boxer_robot()
