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

"""Development-host startup recovery (architecture §12.5).

``recover_startup`` is the required boot hook. Process loops live in
``two.recovery.boot`` so ``two.scheduler`` stays free of git, ACP, and HTTP.
"""

from two.recovery.models import (
    ActionClassification,
    LastActionClass,
    RecoveryReport,
    WorktreeCheck,
)
from two.recovery.recover import EVENT_STARTUP_RECOVERY, recover_startup
from two.recovery.worktree import verify_worktree

__all__ = [
    "EVENT_STARTUP_RECOVERY",
    "ActionClassification",
    "LastActionClass",
    "RecoveryReport",
    "WorktreeCheck",
    "recover_startup",
    "verify_worktree",
]
