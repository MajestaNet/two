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

"""Offline evaluation corpus and promotion-gate runner (architecture §18).

Corpus data lives under ``evals/``. This package loads it, materializes
tiny synthetic git fixtures, and exercises B03–B12 with fakes. It does
not call a Mac, clone production repositories, or declare a model alias
production-ready. Promotion soaks are operator checklists; this runner
never reports them as passed.
"""

from two.evals.models import (
    ArchitectureCase,
    CaseMode,
    CaseOutcome,
    CaseResult,
    EvalMetrics,
    EvalReport,
    EvalTask,
)
from two.evals.runner import live_eval_enabled, run_corpus

__all__ = [
    "ArchitectureCase",
    "CaseMode",
    "CaseOutcome",
    "CaseResult",
    "EvalMetrics",
    "EvalReport",
    "EvalTask",
    "live_eval_enabled",
    "run_corpus",
]
