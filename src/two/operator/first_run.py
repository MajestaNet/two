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

"""First-run device steps for the local operator. No model client.

Vacuum listing and television pairing run here so the harness never sees
a token. Inject list and pair callables in tests. Default tests must not
open a socket.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from two.devices.tv.contract import TvUpstreamError
from two.devices.vacuum.contract import (
    DEFAULT_API_HOST,
    VacuumUpstreamError,
    require_api_host,
    require_token_env,
)
from two.operator.assist import AssistError
from two.operator.hostenv import env_file_path, parse_env_file, upsert_env_value
from two.types import ErrorCode
from two.validation.artifacts import resolve_data_dir

DEFAULT_VACUUM_TOKEN_ENV = "ECO_API_KEY"
DEFAULT_CLIMATE_TOKEN_ENV = "TWO_CLIMATE_TOKEN"
_DEFAULT_ENV_NAMES = (DEFAULT_VACUUM_TOKEN_ENV, DEFAULT_CLIMATE_TOKEN_ENV)

ListNicknames = Callable[[str, str], tuple[str, ...]]
PairSet = Callable[[object], str]
ListApps = Callable[[object], list[tuple[str, str]]]


@dataclass(frozen=True, slots=True)
class EnvNamePresence:
    """Whether one env name has a non-empty value. The value stays off this type."""

    name: str
    present: bool


@dataclass(frozen=True, slots=True)
class AccountListing:
    """Account nicknames. The key stays off this type."""

    token_env: str
    nicknames: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PairStored:
    """Proof the token was written. The token stays off this type."""

    set_id: str
    token_env: str
    stored: bool


@dataclass(frozen=True, slots=True)
class TvAppListing:
    """Application ids for the window and CLI. Not a model tool."""

    set_id: str
    apps: tuple[tuple[str, str], ...]


def env_presence(data_dir: Path | str | None = None) -> tuple[EnvNamePresence, ...]:
    """Named env vars that are present or missing. Does not return values."""
    root = resolve_data_dir(data_dir)
    names: list[str] = []
    seen: set[str] = set()
    for name in (*_DEFAULT_ENV_NAMES, *_token_env_names(root)):
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(EnvNamePresence(name=name, present=_present(root, name)) for name in names)


def list_account(
    slot: str,
    arguments: Mapping[str, object] | None = None,
    *,
    data_dir: Path | str | None = None,
    list_nicknames: ListNicknames | None = None,
) -> AccountListing:
    """List vacuum account nicknames. Does not require an enabled binding."""
    if slot != "vacuum":
        raise AssistError(ErrorCode.INSTALL_ACCOUNT_DENIED.value)
    raw = dict(arguments or {})
    token_env = _vacuum_token_env(raw.get("token_env"), data_dir)
    api_host = _vacuum_api_host(raw.get("api_host"), data_dir)
    token = env_value(data_dir, token_env)
    if token == "":
        raise AssistError(ErrorCode.INSTALL_ENV_MISSING.value)
    lister = list_nicknames if list_nicknames is not None else _ecovacs_nicknames
    try:
        names = lister(api_host, token)
    except VacuumUpstreamError as exc:
        raise AssistError(ErrorCode.VACUUM_UPSTREAM.value) from exc
    nicknames = tuple(item.strip() for item in names if item.strip())
    return AccountListing(token_env=token_env, nicknames=nicknames)


def pair_device(
    slot: str,
    set_id: str,
    *,
    data_dir: Path | str | None = None,
    pair: PairSet | None = None,
) -> PairStored:
    """Pair one bound set and store the token in the data-dir env file.

    The set's brand chooses the handshake. Samsung and LG both return a
    token for ``token_env``. This method writes that token and does not
    return it to the caller beyond the env name.
    """
    if slot != "tv":
        raise AssistError(ErrorCode.INSTALL_PAIR_DENIED.value)
    from two.devices.tv.config import load_tv_config

    install = load_tv_config(data_dir)
    if install is None:
        raise AssistError(ErrorCode.INSTALL_PAIR_DENIED.value)
    policy = install.sets.get(set_id)
    if policy is None:
        raise AssistError(ErrorCode.TV_SET_DENIED.value)
    pairer = pair if pair is not None else _bound_pair
    try:
        token = pairer(policy)
    except TvUpstreamError as exc:
        raise AssistError(ErrorCode.TV_UPSTREAM.value) from exc
    if not isinstance(token, str) or token.strip() == "":
        raise AssistError(ErrorCode.TV_UPSTREAM.value)
    root = resolve_data_dir(data_dir)
    try:
        upsert_env_value(root, policy.token_env, token.strip())
    except ValueError as exc:
        raise AssistError(ErrorCode.INSTALL_PAIR_DENIED.value) from exc
    os.environ[policy.token_env] = token.strip()
    return PairStored(set_id=set_id, token_env=policy.token_env, stored=True)


def list_tv_apps(
    set_id: str,
    *,
    data_dir: Path | str | None = None,
    list_apps: ListApps | None = None,
) -> TvAppListing:
    """List application ids from one bound set. Not advertised to the model."""
    from two.devices.tv.config import load_tv_config

    install = load_tv_config(data_dir)
    if install is None:
        raise AssistError(ErrorCode.INSTALL_PAIR_DENIED.value)
    policy = install.sets.get(set_id)
    if policy is None:
        raise AssistError(ErrorCode.TV_SET_DENIED.value)
    lister = list_apps if list_apps is not None else _bound_apps
    try:
        rows = lister(policy)
    except TvUpstreamError as exc:
        raise AssistError(ErrorCode.TV_UPSTREAM.value) from exc
    cleaned: list[tuple[str, str]] = []
    for app_id, name in rows:
        if not isinstance(app_id, str) or app_id.strip() == "":
            continue
        label = name.strip() if isinstance(name, str) else ""
        cleaned.append((app_id.strip(), label))
    return TvAppListing(set_id=set_id, apps=tuple(cleaned))


def env_value(data_dir: Path | str | None, name: str) -> str:
    """Return the named value from this install's env file, then the process."""
    path = env_file_path(resolve_data_dir(data_dir))
    if path.is_file():
        stored = parse_env_file(path).get(name, "").strip()
        if stored:
            return stored
    return os.environ.get(name, "").strip()


def account_reply(listing: AccountListing) -> str:
    """Redacted operator reply. Nicknames only."""
    if not listing.nicknames:
        return "account nicknames: (none)"
    joined = ", ".join(listing.nicknames)
    return f"account nicknames: {joined}"


def pair_reply(stored: PairStored) -> str:
    """Redacted operator reply. Env name only."""
    return f"stored {stored.token_env} in the data-dir env file"


def _present(data_dir: Path, name: str) -> bool:
    return env_value(data_dir, name) != ""


def _token_env_names(data_dir: Path) -> Sequence[str]:
    names: list[str] = []
    climate = data_dir / "devices" / "climate.yaml"
    if climate.is_file():
        names.extend(_string_fields(climate, "token_env"))
    vacuum = data_dir / "devices" / "vacuum.yaml"
    if vacuum.is_file():
        names.extend(_string_fields(vacuum, "token_env"))
    television = data_dir / "devices" / "tv.yaml"
    if television.is_file():
        names.extend(_tv_token_envs(television))
    cleaned: list[str] = []
    for name in names:
        try:
            cleaned.append(require_token_env(name))
        except ValueError:
            continue
    return cleaned


def _string_fields(path: Path, field: str) -> list[str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    value = raw.get(field)
    return [value] if isinstance(value, str) else []


def _tv_token_envs(path: Path) -> list[str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    sets = raw.get("sets")
    if not isinstance(sets, dict):
        return []
    names: list[str] = []
    for policy in sets.values():
        if not isinstance(policy, dict):
            continue
        token_env = policy.get("token_env")
        if isinstance(token_env, str):
            names.append(token_env)
    return names


def _vacuum_token_env(offered: object, data_dir: Path | str | None) -> str:
    if offered is not None:
        try:
            return require_token_env(offered)
        except ValueError as exc:
            raise AssistError(ErrorCode.INSTALL_ACCOUNT_DENIED.value) from exc
    root = resolve_data_dir(data_dir)
    vacuum = root / "devices" / "vacuum.yaml"
    if vacuum.is_file():
        fields = _string_fields(vacuum, "token_env")
        if fields:
            try:
                return require_token_env(fields[0])
            except ValueError:
                pass
    return DEFAULT_VACUUM_TOKEN_ENV


def _vacuum_api_host(offered: object, data_dir: Path | str | None) -> str:
    if offered is not None:
        try:
            return require_api_host(offered)
        except ValueError as exc:
            raise AssistError(ErrorCode.INSTALL_ACCOUNT_DENIED.value) from exc
    root = resolve_data_dir(data_dir)
    vacuum = root / "devices" / "vacuum.yaml"
    if vacuum.is_file():
        fields = _string_fields(vacuum, "api_host")
        if fields:
            try:
                return require_api_host(fields[0])
            except ValueError:
                pass
    return DEFAULT_API_HOST


def _ecovacs_nicknames(api_host: str, token: str) -> tuple[str, ...]:
    from two.devices.vacuum.ecovacs import EcovacsCloud

    return EcovacsCloud(api_host, token).list_nicknames()


def _bound_pair(policy: object) -> str:
    from two.devices.tv.broker import open_set_client
    from two.devices.tv.contract import SetPolicy

    if not isinstance(policy, SetPolicy):
        raise TvUpstreamError("tv set is not bound")
    return open_set_client(policy, "").pair()


def _bound_apps(policy: object) -> list[tuple[str, str]]:
    from two.devices.tv.broker import open_set_client
    from two.devices.tv.contract import SetPolicy

    if not isinstance(policy, SetPolicy):
        raise TvUpstreamError("tv set is not bound")
    token = os.environ.get(policy.token_env, "")
    return open_set_client(policy, token).applications()
