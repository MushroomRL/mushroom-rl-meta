from copy import deepcopy

import numpy as np

import torch.nn as nn
from mushroom_rl.core import Agent
from mushroom_rl.approximators import Regressor

from mushroom_rl_meta.replay_memory import ReplayMemoryMulty


class ActorLoss(nn.Module):
    def __init__(self, critic):
        super().__init__()

        self._critic = critic

    def forward(self, arg, state, idxs):
        action = arg

        q = self._critic.model.network(state, action, idx=idxs)

        return -q.mean()


class SharedDDPG(Agent):
    def __init__(self, actor_approximator, critic_approximator, policy_class,
                 mdp_info, batch_size, initial_replay_size, max_replay_size,
                 tau, actor_params, critic_params, policy_params,
                 n_actions_per_head, history_length=1, n_input_per_mdp=None,
                 n_games=1, dtype=np.uint8):
        self._dtype = dtype
        self._batch_size = batch_size
        self._n_games = n_games
        if n_input_per_mdp is None:
            self._n_input_per_mdp = [mdp_info.observation_space.shape
                                     for _ in range(self._n_games)]
        else:
            self._n_input_per_mdp = n_input_per_mdp
        self._n_actions_per_head = n_actions_per_head
        self._max_actions = max(n_actions_per_head)[0]
        self._history_length = history_length
        self._tau = tau

        self._replay_memory = [
            ReplayMemoryMulty(initial_replay_size,
                              max_replay_size) for _ in range(self._n_games)
        ]

        self._n_updates = 0

        target_critic_params = deepcopy(critic_params)
        self._critic_approximator = Regressor(critic_approximator,
                                              **critic_params)
        self._target_critic_approximator = Regressor(critic_approximator,
                                                     **target_critic_params)

        if 'loss' not in actor_params:
            actor_params['loss'] = ActorLoss(self._critic_approximator)

        target_actor_params = deepcopy(actor_params)
        self._actor_approximator = Regressor(actor_approximator,
                                             n_fit_targets=2, **actor_params)
        self._target_actor_approximator = Regressor(actor_approximator,
                                                    n_fit_targets=2,
                                                    **target_actor_params)

        self._target_actor_approximator.model.set_weights(
            self._actor_approximator.model.get_weights())
        self._target_critic_approximator.model.set_weights(
            self._critic_approximator.model.get_weights())

        policy = policy_class(self._actor_approximator, **policy_params)

        super().__init__(mdp_info, policy)

        self._allocate_memory()

        self._add_save_attr(
            _dtype='primitive',
            _batch_size='primitive',
            _n_games='primitive',
            _n_input_per_mdp='primitive',
            _n_action_per_head='primitive',
            _history_length='primitive',
            _tau='primitive',
            _max_actions='primitive',
            _replay_memory='mushroom',
            _n_updates='primitive',
            _critic_approximator='mushroom',
            _target_critic_approximator='mushroom',
            _actor_approximator='mushroom',
            _target_actor_approximator='mushroom',
        )

    def fit(self, dataset):
        s = np.array([d[0][0] for d in dataset]).ravel()
        games = np.unique(s)
        for g in games:
            idxs = np.argwhere(s == g).ravel()
            d = list()
            for idx in idxs:
                d.append(dataset[idx])

            self._replay_memory[g].add(d)

        fit_condition = np.all([rm.initialized for rm in self._replay_memory])

        if fit_condition:
            for i in range(len(self._replay_memory)):
                game_state, game_action, game_reward, game_next_state,\
                    game_absorbing, _ = self._replay_memory[i].get(
                        self._batch_size)

                start = self._batch_size * i
                stop = start + self._batch_size

                self._state_idxs[start:stop] = np.ones(self._batch_size) * i
                self._state[start:stop, :self._n_input_per_mdp[i][0]] = game_state
                self._action[start:stop, :self._n_actions_per_head[i][0]] = game_action
                self._reward[start:stop] = game_reward
                self._next_state_idxs[start:stop] = np.ones(self._batch_size) * i
                self._next_state[start:stop, :self._n_input_per_mdp[i][0]] = game_next_state
                self._absorbing[start:stop] = game_absorbing

            q_next = self._next_q()
            q = self._reward + q_next

            self._critic_approximator.fit(self._state, self._action, q,
                                          idx=self._state_idxs)
            self._actor_approximator.fit(self._state, self._state,
                                         self._state_idxs,
                                         idx=self._state_idxs)

            self._n_updates += 1

            self._update_target()

    def get_shared_weights(self):
        cw = self._critic_approximator.model.network.get_shared_weights()
        aw = self._actor_approximator.model.network.get_shared_weights()

        return [cw, aw]

    def set_shared_weights(self, weights):
        self._critic_approximator.model.network.set_shared_weights(weights[0])
        self._actor_approximator.model.network.set_shared_weights(weights[1])

    def freeze_shared_weights(self):
        self._critic_approximator.model.network.freeze_shared_weights()
        self._actor_approximator.model.network.freeze_shared_weights()

    def unfreeze_shared_weights(self):
        self._critic_approximator.model.network.unfreeze_shared_weights()
        self._actor_approximator.model.network.unfreeze_shared_weights()

    def _allocate_memory(self):
        n_samples = self._batch_size * self._n_games
        self._state_idxs = np.zeros(n_samples, dtype=np.int)
        self._state = np.zeros(
            ((n_samples,
             self._history_length) + self.mdp_info.observation_space.shape),
            dtype=self._dtype
        ).squeeze()
        self._action = np.zeros((n_samples, self._max_actions))
        self._reward = np.zeros(n_samples)
        self._next_state_idxs = np.zeros(n_samples, dtype=np.int)
        self._next_state = np.zeros(
            ((n_samples,
             self._history_length) + self.mdp_info.observation_space.shape),
            dtype=self._dtype
        ).squeeze()
        self._absorbing = np.zeros(n_samples)

    def _update_target(self):
        """
        Update the target networks.

        """
        critic_weights = self._tau * self._critic_approximator.model.get_weights()
        critic_weights += (1 - self._tau) * self._target_critic_approximator.get_weights()
        self._target_critic_approximator.set_weights(critic_weights)

        actor_weights = self._tau * self._actor_approximator.model.get_weights()
        actor_weights += (1 - self._tau) * self._target_actor_approximator.get_weights()
        self._target_actor_approximator.set_weights(actor_weights)

    def _next_q(self):
        a = self._target_actor_approximator(self._next_state,
                                            idx=self._next_state_idxs)
        q = self._target_critic_approximator(self._next_state, a,
                                             idx=self._next_state_idxs).ravel()

        out_q = np.zeros(self._batch_size * self._n_games)
        for i in range(self._n_games):
            start = self._batch_size * i
            stop = start + self._batch_size

            out_q[start:stop] = q[start:stop] * self.mdp_info.gamma[i]
            if np.any(self._absorbing[start:stop]):
                out_q[start:stop] = out_q[start:stop] * (
                    1 - self._absorbing[start:stop]
                )

        return out_q

    def _post_load(self):
        self._actor_approximator = self.policy._approximator
        self._allocate_memory()
