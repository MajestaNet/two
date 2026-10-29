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

"""In-repo device packages. Each protocol has its own ADR.

Importing this package does not enable a slot, open a socket, or read
secrets. See ADR 0022, ADR 0027, ADR 0029, ADR 0038, ADR 0043, and
``config/adapters/catalog.yaml``.
"""
