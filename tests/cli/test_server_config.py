from os import listdir, path
from pathlib import Path
from unittest.mock import patch

import pytest

from mcpengine.cli.server import (
    Input,
    Requirement,
    ServerConfig,
    get_config,
    prompt_config,
)

CURRENT_PATH = path.dirname(__file__)
CONFIG_DIR_PATH = path.join(CURRENT_PATH, "./configs")
VALID_CONFIG_DIR_PATH = path.join(CONFIG_DIR_PATH, "valid")
INVALID_CONFIG_DIR_PATH = path.join(CONFIG_DIR_PATH, "invalid")


def test_empty_config():
    """Tests a minimal server config file to be parsed properly."""
    config = get_config(Path(path.join(VALID_CONFIG_DIR_PATH, "empty.yaml")))

    assert config.name == "empty"
    assert config.version == "v1"
    assert config.description is not None
    assert config.command == "ls"
    assert config.requires == []
    assert config.inputs == []
    assert config.env == {}


def test_full_config():
    """Tests a server config is parsed and templated properly."""
    config = get_config(Path(path.join(VALID_CONFIG_DIR_PATH, "full.yaml")))

    assert config.name == "full"
    assert config.version == "v1"
    assert config.description is not None
    # This happens before input templating, so the command still has
    # templates in it.
    assert config.command == "ls ${input1} ${input2}"
    assert config.env == {
        "env1": "${input1}-value",
        "env2": "${input2}-value",
    }
    assert config.requires == [
        Requirement(
            name="docker",
            install_hint="docker install hint",
        ),
        Requirement(
            name="npx",
            install_hint="npx install hint",
        ),
    ]
    assert config.inputs == [
        Input(
            name="input1",
            type="text",
            message="Please input input1",
            default="input1-default",
        ),
        Input(
            name="input2",
            type="choice",
            message="Please input input2",
            default="input2-default",
            choices=[
                "input2-default",
                "another input",
                "something",
            ],
        ),
    ]

    config.template_config({
        "input1": "template1",
        "input2": "template2",
    })

    assert config.command == "ls template1 template2"
    assert config.env == {
        "env1": "template1-value",
        "env2": "template2-value",
    }


def test_invalid_configs():
    """Tests all the invalid configs to ensure that they throw an Exception."""
    for invalid_config in listdir(INVALID_CONFIG_DIR_PATH):
        with pytest.raises(Exception):
            get_config(Path(path.join(INVALID_CONFIG_DIR_PATH, invalid_config)))


def test_command_template():
    """Tests that the templating in the run_command works after obtaining inputs."""
    config = ServerConfig(
        name="test",
        version="v1",
        description="test",
        inputs=[
            Input(name="input1", type="text", message="input1"),
            Input(name="input2", type="text", message="input2"),
        ],
        command="cat ${input1} ${input2}",
    )
    prompt_return_value = {
        "input1": "input1-value",
        "input2": "input2-value",
    }

    prompt_input_path = "mcpengine.cli.server._prompt_inputs"
    with patch(prompt_input_path) as mock_prompt_inputs:
        mock_prompt_inputs.return_value = prompt_return_value

        config = prompt_config(config)
        assert config.command == "cat input1-value input2-value"
