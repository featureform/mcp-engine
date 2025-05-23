"""MCP CLI tools."""

import importlib.metadata
import importlib.util
import os
import shlex
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

from mcpengine.cli.docker import PROXY_IMAGE_NAME
from mcpengine.cli.server import get_config, prompt_command

try:
    import docker
    import typer
except ImportError:
    print("Error: cli feature is required. Install with 'pip install mcpengine[cli]'")
    sys.exit(1)

try:
    from mcpengine.cli import claude
    from mcpengine.server.mcpengine.utilities.logging import get_logger
except ImportError:
    print("Error: mcpengine.server.mcpengine is not installed or not in PYTHONPATH")
    sys.exit(1)

try:
    import dotenv
except ImportError:
    dotenv = None

logger = get_logger("cli")

app = typer.Typer(
    name="mcpengine",
    help="MCP development tools",
    add_completion=False,
    no_args_is_help=True,  # Show help if no args provided
)


def _get_npx_command():
    """Get the correct npx command for the current platform."""
    if sys.platform == "win32":
        # Try both npx.cmd and npx.exe on Windows
        for cmd in ["npx.cmd", "npx.exe", "npx"]:
            try:
                subprocess.run(
                    [cmd, "--version"], check=True, capture_output=True, shell=True
                )
                return cmd
            except subprocess.CalledProcessError:
                continue
        return None
    return "npx"  # On Unix-like systems, just use npx


def _parse_env_var(env_var: str) -> tuple[str, str]:
    """Parse environment variable string in format KEY=VALUE."""
    if "=" not in env_var:
        logger.error(
            f"Invalid environment variable format: {env_var}. Must be KEY=VALUE"
        )
        sys.exit(1)
    key, value = env_var.split("=", 1)
    return key.strip(), value.strip()


def _build_uv_command(
    file_spec: str,
    with_editable: Path | None = None,
    with_packages: list[str] | None = None,
) -> list[str]:
    """Build the uv run command that runs a MCP server through mcpengine run."""
    cmd = ["uv"]

    cmd.extend(["run", "--with", "mcpengine"])

    if with_editable:
        cmd.extend(["--with-editable", str(with_editable)])

    if with_packages:
        for pkg in with_packages:
            if pkg:
                cmd.extend(["--with", pkg])

    # Add mcpengine run command
    cmd.extend(["mcpengine", "run", file_spec])
    return cmd


def _parse_file_path(file_spec: str) -> tuple[Path, str | None]:
    """Parse a file path that may include a server object specification.

    Args:
        file_spec: Path to file, optionally with :object suffix

    Returns:
        Tuple of (file_path, server_object)
    """
    # First check if we have a Windows path (e.g., C:\...)
    has_windows_drive = len(file_spec) > 1 and file_spec[1] == ":"

    # Split on the last colon, but only if it's not part of the Windows drive letter
    # and there's actually another colon in the string after the drive letter
    if ":" in (file_spec[2:] if has_windows_drive else file_spec):
        file_str, server_object = file_spec.rsplit(":", 1)
    else:
        file_str, server_object = file_spec, None

    # Resolve the file path
    file_path = Path(file_str).expanduser().resolve()
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)
    if not file_path.is_file():
        logger.error(f"Not a file: {file_path}")
        sys.exit(1)

    return file_path, server_object


def _import_server(file: Path, server_object: str | None = None):
    """Import a MCP server from a file.

    Args:
        file: Path to the file
        server_object: Optional object name in format "module:object" or just "object"

    Returns:
        The server object
    """
    # Add parent directory to Python path so imports can be resolved
    file_dir = str(file.parent)
    if file_dir not in sys.path:
        sys.path.insert(0, file_dir)

    # Import the module
    spec = importlib.util.spec_from_file_location("server_module", file)
    if not spec or not spec.loader:
        logger.error("Could not load module", extra={"file": str(file)})
        sys.exit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # If no object specified, try common server names
    if not server_object:
        # Look for the most common server object names
        for name in ["mcpengine", "mcp", "server", "app"]:
            if hasattr(module, name):
                return getattr(module, name)

        logger.error(
            f"No server object found in {file}. Please either:\n"
            "1. Use a standard variable name (mcpengine, mcp, server, or app)\n"
            "2. Specify the object name with file:object syntax",
            extra={"file": str(file)},
        )
        sys.exit(1)

    # Handle module:object syntax
    if ":" in server_object:
        module_name, object_name = server_object.split(":", 1)
        try:
            server_module = importlib.import_module(module_name)
            server = getattr(server_module, object_name, None)
        except ImportError:
            logger.error(
                f"Could not import module '{module_name}'",
                extra={"file": str(file)},
            )
            sys.exit(1)
    else:
        # Just object name
        server = getattr(module, server_object, None)

    if server is None:
        logger.error(
            f"Server object '{server_object}' not found",
            extra={"file": str(file)},
        )
        sys.exit(1)

    return server


@app.command()
def version() -> None:
    """Show the MCP version."""
    try:
        version = importlib.metadata.version("mcpengine")
        print(f"MCP version {version}")
    except importlib.metadata.PackageNotFoundError:
        print("MCP version unknown (package not installed)")
        sys.exit(1)


@app.command()
def dev(
    file_spec: str = typer.Argument(
        ...,
        help="Python file to run, optionally with :object suffix",
    ),
    with_editable: Annotated[
        Path | None,
        typer.Option(
            "--with-editable",
            "-e",
            help="Directory containing pyproject.toml to install in editable mode",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    with_packages: Annotated[
        list[str],
        typer.Option(
            "--with",
            help="Additional packages to install",
        ),
    ] = [],
) -> None:
    """Run a MCP server with the MCP Inspector."""
    file, server_object = _parse_file_path(file_spec)

    logger.debug(
        "Starting dev server",
        extra={
            "file": str(file),
            "server_object": server_object,
            "with_editable": str(with_editable) if with_editable else None,
            "with_packages": with_packages,
        },
    )

    try:
        # Import server to get dependencies
        server = _import_server(file, server_object)
        if hasattr(server, "dependencies"):
            with_packages = list(set(with_packages + server.dependencies))

        uv_cmd = _build_uv_command(file_spec, with_editable, with_packages)

        # Get the correct npx command
        npx_cmd = _get_npx_command()
        if not npx_cmd:
            logger.error(
                "npx not found. Please ensure Node.js and npm are properly installed "
                "and added to your system PATH."
            )
            sys.exit(1)

        # Run the MCP Inspector command with shell=True on Windows
        shell = sys.platform == "win32"
        process = subprocess.run(
            [npx_cmd, "@modelcontextprotocol/inspector"] + uv_cmd,
            check=True,
            shell=shell,
            env=dict(os.environ.items()),  # Convert to list of tuples for env update
        )
        sys.exit(process.returncode)
    except subprocess.CalledProcessError as e:
        logger.error(
            "Dev server failed",
            extra={
                "file": str(file),
                "error": str(e),
                "returncode": e.returncode,
            },
        )
        sys.exit(e.returncode)
    except FileNotFoundError:
        logger.error(
            "npx not found. Please ensure Node.js and npm are properly installed "
            "and added to your system PATH. You may need to restart your terminal "
            "after installation.",
            extra={"file": str(file)},
        )
        sys.exit(1)


@app.command()
def run(
    file_spec: str = typer.Argument(
        ...,
        help="Python file to run, optionally with :object suffix",
    ),
    transport: Annotated[
        str | None,
        typer.Option(
            "--transport",
            "-t",
            help="Transport protocol to use (stdio or sse)",
        ),
    ] = None,
) -> None:
    """Run a MCP server.

    The server can be specified in two ways:\n
    1. Module approach: server.py - runs the module directly, expecting a server.run() call.\n
    2. Import approach: server.py:app - imports and runs the specified server object.\n\n

    Note: This command runs the server directly. You are responsible for ensuring
    all dependencies are available.\n
    For dependency management, use `mcpengine install` or `mcpengine dev` instead.
    """  # noqa: E501
    file, server_object = _parse_file_path(file_spec)

    logger.debug(
        "Running server",
        extra={
            "file": str(file),
            "server_object": server_object,
            "transport": transport,
        },
    )

    try:
        # Import and get server object
        server = _import_server(file, server_object)

        # Run the server
        kwargs = {}
        if transport:
            kwargs["transport"] = transport

        server.run(**kwargs)

    except Exception as e:
        logger.error(
            f"Failed to run server: {e}",
            extra={
                "file": str(file),
                "error": str(e),
            },
        )
        sys.exit(1)


@app.command()
def install(
    file_spec: str = typer.Argument(
        ...,
        help="Python file to run, optionally with :object suffix",
    ),
    server_name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help="Custom name for the server (defaults to server's name attribute or"
            " file name)",
        ),
    ] = None,
    with_editable: Annotated[
        Path | None,
        typer.Option(
            "--with-editable",
            "-e",
            help="Directory containing pyproject.toml to install in editable mode",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    with_packages: Annotated[
        list[str],
        typer.Option(
            "--with",
            help="Additional packages to install",
        ),
    ] = [],
    env_vars: Annotated[
        list[str],
        typer.Option(
            "--env-var",
            "-v",
            help="Environment variables in KEY=VALUE format",
        ),
    ] = [],
    env_file: Annotated[
        Path | None,
        typer.Option(
            "--env-file",
            "-f",
            help="Load environment variables from a .env file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Install a MCP server in the Claude desktop app.

    Environment variables are preserved once added and only updated if new values
    are explicitly provided.
    """
    file, server_object = _parse_file_path(file_spec)

    logger.debug(
        "Installing server",
        extra={
            "file": str(file),
            "server_name": server_name,
            "server_object": server_object,
            "with_editable": str(with_editable) if with_editable else None,
            "with_packages": with_packages,
        },
    )

    if not claude.get_claude_config_path():
        logger.error("Claude app not found")
        sys.exit(1)

    # Try to import server to get its name, but fall back to file name if dependencies
    # missing
    name = server_name
    server = None
    if not name:
        try:
            server = _import_server(file, server_object)
            name = server.name
        except (ImportError, ModuleNotFoundError) as e:
            logger.debug(
                "Could not import server (likely missing dependencies), using file"
                " name",
                extra={"error": str(e)},
            )
            name = file.stem

    # Get server dependencies if available
    server_dependencies = getattr(server, "dependencies", []) if server else []
    if server_dependencies:
        with_packages = list(set(with_packages + server_dependencies))

    # Process environment variables if provided
    env_dict: dict[str, str] | None = None
    if env_file or env_vars:
        env_dict = {}
        # Load from .env file if specified
        if env_file:
            if dotenv:
                try:
                    env_dict |= {
                        k: v
                        for k, v in dotenv.dotenv_values(env_file).items()
                        if v is not None
                    }
                except Exception as e:
                    logger.error(f"Failed to load .env file: {e}")
                    sys.exit(1)
            else:
                logger.error("python-dotenv is not installed. Cannot load .env file.")
                sys.exit(1)

        # Add command line environment variables
        for env_var in env_vars:
            key, value = _parse_env_var(env_var)
            env_dict[key] = value

    if claude.update_claude_config(
        file_spec,
        name,
        with_editable=with_editable,
        with_packages=with_packages,
        env_vars=env_dict,
    ):
        logger.info(f"Successfully installed {name} in Claude app")
    else:
        logger.error(f"Failed to install {name} in Claude app")
        sys.exit(1)


class TransportMode(str, Enum):
    http = "http"
    sse = "sse"


@app.command()
def add(
    path: Annotated[
        Path, typer.Argument(help="The path of the MCP server file config to add.")
    ],
    install_claude: Annotated[
        bool, typer.Option("--claude", help="Add the installation to Claude config.")
    ] = False,
):
    """Adds an MCP server via a config file."""
    config = get_config(path)
    command = prompt_command(config)

    split_command = shlex.split(command)
    command, args = split_command[0], split_command[1:]

    # This check is here for when future installation targets are added.
    if not install_claude:
        logger.warning("No installation target specified.")
        sys.exit(1)

    if install_claude:
        if claude.update_server_config(
            name=config.name,
            entry={
                "command": command,
                "args": args,
            },
        ):
            logger.info(f"Successfully installed {config.name} in Claude app")
        else:
            logger.error(f"Failed to install {config.name} in Claude app")
            sys.exit(1)


@app.command()
def proxy(
    name: Annotated[
        str, typer.Argument(help="The name to associate with the MCP server.")
    ],
    host_endpoint: Annotated[
        str,
        typer.Argument(
            help="The endpoint of the running MCP server.",
        ),
    ],
    mode: Annotated[
        TransportMode,
        typer.Option("--mode", "-m", help="The transport mode of the MCP server."),
    ] = TransportMode.sse,
    port: Annotated[
        int,
        typer.Option(
            "--port",
            "-p",
        ),
    ] = 8181,
    client_id: Annotated[
        str | None,
        typer.Option(
            "--client-id",
            help="The client id of the IdP used by the MCP server.",
        ),
    ] = None,
    client_secret: Annotated[
        str | None,
        typer.Option(
            "--client-secret",
            help="The client secret of the IdP used by the MCP server.",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            "-d",
            help="Enable debug mode for more verbose logs.",
        ),
    ] = False,
    install_claude: Annotated[
        bool, typer.Option("--claude", help="Add the installation to Claude config.")
    ] = False,
) -> None:
    """Install a proxy to an MCP server.

    Environment variables are preserved once added and only updated if new values
    are explicitly provided.
    """
    logger.debug(
        "Installing server",
        extra={
            "server_name": name,
            "host_endpoint": host_endpoint,
            "mode": mode.value,
            "client_id": client_id,
            "client_secret": "*" * len(client_secret) if client_secret else None,
            "debug": debug,
        },
    )

    client = docker.from_env()

    logger.debug("Pulling latest version of mcpengine-proxy")
    client.images.pull(PROXY_IMAGE_NAME, "latest")

    # This check is here for when future installation targets are added.
    if not install_claude:
        logger.warning("No installation target specified.")
        sys.exit(1)

    if install_claude:
        if claude.install_proxy(
            name=name,
            host_endpoint=host_endpoint,
            port=port,
            client_id=client_id,
            client_secret=client_secret,
            mode=mode.value,
            debug=debug,
        ):
            logger.info(f"Successfully installed {name} in Claude app")
        else:
            logger.error(f"Failed to install {name} in Claude app")
            sys.exit(1)
