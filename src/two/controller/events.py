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

"""Append-only workflow event types. One event per stage transition."""

EVENT_STAGE = "workflow.stage"
EVENT_INTAKE = "workflow.intake"
EVENT_ISOLATE = "workflow.isolate"
EVENT_INSPECT = "workflow.inspect"
EVENT_PLAN = "task.plan"
EVENT_IMPLEMENT = "workflow.implement"
EVENT_VALIDATION = "task.validation"
EVENT_REPAIR = "workflow.repair"
EVENT_REVIEW = "workflow.review"
EVENT_REPORT = "workflow.report"
EVENT_COMPLETE = "workflow.complete"
EVENT_BLOCKED = "workflow.blocked"
EVENT_FAILED = "workflow.failed"
EVENT_NO_PROGRESS = "workflow.no_progress"
EVENT_DIFF = "task.diff"
EVENT_BLOCKER = "task.blocker"
EVENT_WORKER = "workflow.worker"
