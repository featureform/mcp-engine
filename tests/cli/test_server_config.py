from os import listdir, path
from unittest.mock import patch

import pytest

from mcpengine.cli.server import (
    Input,
    Requirement,
    ServerConfig,
    get_config,
    prompt_command,
)

CONFIG_DIR_PATH = "./configs"
VALID_CONFIG_DIR_PATH = "./configs/valid"
INVALID_CONFIG_DIR_PATH = "./configs/invalid"

def test_empty_config():
    """Tests a minimal server config file to be parsed properly."""
    config = get_config(path.join(VALID_CONFIG_DIR_PATH, "empty.yaml"))

    assert config.name == "empty"
    assert config.version == "v1"
    assert config.description is not None
    assert config.command == "ls"
    assert config.requires == []
    assert config.inputs == []

def test_full_config():
    """Tests a server config with all optional sections to be parsed properly."""
    config = get_config(path.join(VALID_CONFIG_DIR_PATH, "full.yaml"))

    assert config.name == "full"
    assert config.version == "v1"
    assert config.description is not None
    assert config.command == "ls"
    assert config.requires == [
        Requirement(
            name="docker",
            version="1.0",
            install_hint="docker install hint",
        ),
        Requirement(
            name= "npx",
            version= "1.0",
            install_hint= "npx install hint",
        )
    ]
    assert config.inputs == [
        Input(
            name= "input1",
            type= "text",
            message= "Please input input1",
            default= "input1-default",
        ),
        Input(
            name= "input2",
            type= "choice",
            message= "Please input input2",
            default= "input2-default",
            choices= [
                "input2-default",
                "another input",
                "something",
            ]
        )
    ]

def test_invalid_configs():
    """Tests all the invalid configs to ensure that they throw an Exception."""
    for invalid_config in listdir(INVALID_CONFIG_DIR_PATH):
        with pytest.raises(Exception):
            get_config(path.join(INVALID_CONFIG_DIR_PATH, invalid_config))

def test_command_template():
    """Tests that the templating in the run_command works after obtaining inputs."""
    config = ServerConfig(
        name="test",
        version="v1",
        description="test",
        inputs=[
            Input(name="input1", type= "text", message= "input1"),
            Input(name="input2", type= "text", message= "input2"),
        ],
        command="cat ${input1} ${input2}"
    )
    prompt_return_value=  {
        "input1": "input1-value",
        "input2": "input2-value",
    }

    prompt_input_path = "mcpengine.cli.server._prompt_inputs"
    with patch(prompt_input_path) as mock_prompt_inputs:
        mock_prompt_inputs.return_value = prompt_return_value

        command = prompt_command(config)
        assert command == "cat input1-value input2-value"

