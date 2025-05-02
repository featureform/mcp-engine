import os
from importlib import resources
from pathlib import Path
from shutil import which
from string import Template
from typing import Any

import yaml
from pydantic import BaseModel, Field
from questionary import prompt


class Requirement(BaseModel):
    name: str
    install_hint: str


class Input(BaseModel):
    name: str
    type: str
    message: str
    default: Any = None
    choices: list[str] | None = None


class ServerConfig(BaseModel):
    name: str
    version: str
    description: str
    requires: list[Requirement] = Field(default_factory=list)
    inputs: list[Input] = Field(default_factory=list)
    command: str
    env: dict[str, str] = Field(default_factory=dict)

    def template_config(self, inputs: dict[str, str]):
        template_string = Template(self.command)
        self.command = template_string.safe_substitute(**inputs)

        for key, value in self.env.items():
            template_string = Template(value)
            self.env[key] = template_string.safe_substitute(**inputs)


def get_builtin_config_path(config_name: str) -> Path:
    filename = config_name + ".yaml"
    traversable = resources.files("mcpengine.cli.configs") / filename
    with resources.as_file(traversable) as path:
        return path


def _load_config_file(config_path: Path) -> dict[str, Any]:
    try:
        builtin_config_path = get_builtin_config_path(str(config_path))
        if os.path.isfile(builtin_config_path):
            with open(builtin_config_path) as config_file:
                return yaml.safe_load(config_file)

        with open(config_path) as file:
            return yaml.safe_load(file)
    except Exception as e:
        raise Exception(f"Config '{config_path}' not found") from e


def _prompt_inputs(inputs: list[Input]) -> dict[str, str]:
    # Removing unused parameters.
    questions: list[dict[str, Any]] = []
    for model in inputs:
        result: dict[str, Any] = {}
        for field_name in model.model_fields.keys():
            field_value = getattr(model, field_name)
            if field_value is None:
                continue
            result[str(field_name)] = field_value
        questions.append(result)

    return prompt(questions)


def get_config(config_path: Path) -> ServerConfig:
    file_data = _load_config_file(config_path)
    config = ServerConfig(**file_data)
    if config.version != "v1":
        raise ValueError(f"Unsupported version: {config.version}")
    return config


def prompt_config(config: ServerConfig) -> ServerConfig:
    updated_config = config.model_copy(deep=True)

    for requirement in updated_config.requires:
        if which(requirement.name) is None:
            raise ValueError(
                f"Requirement {requirement.name} is not installed: "
                f"{requirement.install_hint}"
            )

    inputs = _prompt_inputs(updated_config.inputs)
    updated_config.template_config(inputs)
    return updated_config
