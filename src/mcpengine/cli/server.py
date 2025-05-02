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


def _load_config_file(config_path: Path) -> ServerConfig:
    try:
        with open(config_path) as file:
            data = yaml.safe_load(file)
            return ServerConfig(**data)
    except Exception as e:
        raise Exception(f"Failed to load configuration from {config_path}") from e


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


def get_builtin_config(config_name):
    """
    Get a builtin config file by name.

    Args:
        config_name: Name of the config file (without path)

    Returns:
        Path to the config file
    """
    with resources.files("mcpengine.cli.configs").joinpath(config_name) as config_path:
        return str(config_path)


def get_config(config_path: Path) -> ServerConfig:
    config = _load_config_file(config_path)
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
