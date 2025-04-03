# Copyright (c) 2025 Featureform, Inc.
#
# Licensed under the MIT License. See LICENSE file in the
# project root for full license information.

from dataclasses import dataclass


@dataclass
class UserContext:
    name: str | None
    email: str | None
    sid: str | None
