# This file is part of sbi, a toolkit for simulation-based inference. sbi is licensed
# under the Affero General Public License v3, see <https://www.gnu.org/licenses/>.

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import torch
import torch.distributions.transforms as torch_tf
from torch import Tensor, nn

from sbi.inference.potentials.base_potential import BasePotential
from sbi.utils import mcmc_transform
from sbi.utils.sbiutils import match_theta_and_x_batch_shapes, within_support
from sbi.utils.torchutils import ensure_theta_batched
from sbi.types import TorchTransform


def posterior_estimator_based_potential(
    posterior_estimator: nn.Module,
    prior: Any,
    x_o: Optional[Tensor],
) -> Tuple[Callable, TorchTransform]:
    r"""Returns the potential for posterior-based methods.

    It also returns a transformation that can be used to transform the potential into
    unconstrained space.

    The potential is the same as the log-probability of the `posterior_estimator`, but
    it is set to $-\inf$ outside of the prior bounds.

    Args:
        posterior_estimator: The neural network modelling the posterior.
        prior: The prior distribution.
        x_o: The observed data at which to evaluate the posterior.

    Returns:
        The potential function and a transformation that maps
        to unconstrained space.
    """

    device = str(next(posterior_estimator.parameters()).device)

    potential_fn = PosteriorBasedPotential(
        posterior_estimator, prior, x_o, device=device
    )
    theta_transform = mcmc_transform(prior, device=device)

    return potential_fn, theta_transform


class PosteriorBasedPotential(BasePotential):
    allow_iid_x = False  # type: ignore

    def __init__(
        self,
        posterior_estimator: nn.Module,
        prior: Any,
        x_o: Optional[Tensor],
        device: str = "cpu",
    ):
        r"""Returns the potential for posterior-based methods.

        The potential is the same as the log-probability of the `posterior_estimator`,
        but it is set to $-\inf$ outside of the prior bounds.

        Args:
            posterior_estimator: The neural network modelling the posterior.
            prior: The prior distribution.
            x_o: The observed data at which to evaluate the posterior.

        Returns:
            The potential function.
        """
        super().__init__(prior, x_o, device)
        self.posterior_estimator = posterior_estimator
        self.posterior_estimator.eval()

    def __call__(self, theta: Tensor, track_gradients: bool = True) -> Tensor:
        r"""Returns the potential for posterior-based methods.

        Args:
            theta: The parameter set at which to evaluate the potential function.
            track_gradients: Whether to track the gradients.

        Returns:
            The potential.
        """

        theta = ensure_theta_batched(torch.as_tensor(theta))
        theta, x_repeated = match_theta_and_x_batch_shapes(theta, self.x_o)
        theta, x_repeated = theta.to(self.device), x_repeated.to(self.device)

        with torch.set_grad_enabled(track_gradients):
            posterior_log_prob = self.posterior_estimator.log_prob(
                theta, context=x_repeated
            )

            # Force probability to be zero outside prior support.
            in_prior_support = within_support(self.prior, theta)

            posterior_log_prob = torch.where(
                in_prior_support,
                posterior_log_prob,
                torch.tensor(float("-inf"), dtype=torch.float32, device=self.device),
            )
        return posterior_log_prob
