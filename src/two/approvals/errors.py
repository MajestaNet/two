# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

"""Approvals and cooperative-lifecycle failures. Not store I/O."""

from __future__ import annotations


class ApprovalsError(Exception):
    """Base class for question, approval, and pause/resume/cancel failures."""


class StaleDigestError(ApprovalsError):
    """The decide request digest does not match the stored immutable digest."""

    def __init__(self, *, expected: str, offered: str) -> None:
        self.expected = expected
        self.offered = offered
        super().__init__(f"stale action digest: stored {expected!r}, request {offered!r}")


class TerminalLifecycleError(ApprovalsError):
    """The task is in a terminal lifecycle and the requested transition is refused."""


class NotResumableError(ApprovalsError):
    """Resume is only allowed from paused or awaiting_input."""


class UnsafeTimeoutDefaultError(ApprovalsError):
    """A timeout default would treat silence as a side-effecting decision."""


class PrincipalRequiredError(ApprovalsError):
    """A deciding principal id is required and must be non-empty after normalize."""
