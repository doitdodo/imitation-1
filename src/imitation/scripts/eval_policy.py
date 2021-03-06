import contextlib
import os
import os.path as osp
import time
from typing import Optional

import tensorflow as tf
from sacred.observers import FileStorageObserver
from stable_baselines.common.vec_env import VecEnvWrapper

import imitation.util.sacred as sacred_util
from imitation.data import rollout
from imitation.policies import serialize
from imitation.rewards.serialize import load_reward
from imitation.scripts.config.eval_policy import eval_policy_ex
from imitation.util import reward_wrapper, util


class InteractiveRender(VecEnvWrapper):
    def __init__(self, venv, fps):
        super().__init__(venv)
        self.render_fps = fps

    def reset(self):
        ob = self.venv.reset()
        self.venv.render()
        return ob

    def step_wait(self):
        ob = self.venv.step_wait()
        if self.render_fps > 0:
            time.sleep(1 / self.render_fps)
        self.venv.render()
        return ob


@eval_policy_ex.main
def eval_policy(
    _run,
    _seed: int,
    env_name: str,
    eval_n_timesteps: Optional[int],
    eval_n_episodes: Optional[int],
    num_vec: int,
    parallel: bool,
    render: bool,
    render_fps: int,
    log_dir: str,
    policy_type: str,
    policy_path: str,
    reward_type: Optional[str] = None,
    reward_path: Optional[str] = None,
    max_episode_steps: Optional[int] = None,
):
    """Rolls a policy out in an environment, collecting statistics.

    Args:
      _seed: generated by Sacred.
      env_name: Gym environment identifier.
      eval_n_timesteps: Minimum number of timesteps to evaluate for. Set exactly
          one of `eval_n_episodes` and `eval_n_timesteps`.
      eval_n_episodes: Minimum number of episodes to evaluate for. Set exactly
          one of `eval_n_episodes` and `eval_n_timesteps`.
      num_vec: Number of environments to run simultaneously.
      parallel: If True, use `SubprocVecEnv` for true parallelism; otherwise,
          uses `DummyVecEnv`.
      max_episode_steps: If not None, then environments are wrapped by
          TimeLimit so that they have at most `max_episode_steps` steps per
          episode.
      render: If True, renders interactively to the screen.
      log_dir: The directory to log intermediate output to. (As of 2019-07-19
          this is just episode-by-episode reward from bench.Monitor.)
      policy_type: A unique identifier for the saved policy,
          defined in POLICY_CLASSES.
      policy_path: A path to the serialized policy.
      reward_type: If specified, overrides the environment reward with
          a reward of this.
      reward_path: If reward_type is specified, the path to a serialized reward
          of `reward_type` to override the environment reward with.

    Returns:
      Return value of `imitation.util.rollout.rollout_stats()`.
    """
    os.makedirs(log_dir, exist_ok=True)
    sacred_util.build_sacred_symlink(log_dir, _run)

    tf.logging.set_verbosity(tf.logging.INFO)
    tf.logging.info("Logging to %s", log_dir)
    sample_until = rollout.make_sample_until(eval_n_timesteps, eval_n_episodes)
    venv = util.make_vec_env(
        env_name,
        num_vec,
        seed=_seed,
        parallel=parallel,
        log_dir=log_dir,
        max_episode_steps=max_episode_steps,
    )

    if render:
        venv = InteractiveRender(venv, render_fps)
    # TODO(adam): add support for videos using VideoRecorder?

    with contextlib.ExitStack() as stack:
        if reward_type is not None:
            reward_fn_ctx = load_reward(reward_type, reward_path, venv)
            reward_fn = stack.enter_context(reward_fn_ctx)
            venv = reward_wrapper.RewardVecEnvWrapper(venv, reward_fn)
            tf.logging.info(f"Wrapped env in reward {reward_type} from {reward_path}.")

        with serialize.load_policy(policy_type, policy_path, venv) as policy:
            trajs = rollout.generate_trajectories(policy, venv, sample_until)
    return rollout.rollout_stats(trajs)


def main_console():
    observer = FileStorageObserver(osp.join("output", "sacred", "eval_policy"))
    eval_policy_ex.observers.append(observer)
    eval_policy_ex.run_commandline()


if __name__ == "__main__":  # pragma: no cover
    main_console()
