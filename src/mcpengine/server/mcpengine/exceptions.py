"""Custom exceptions for MCPEngine."""


class MCPEngineError(Exception):
    """Base error for MCPEngine."""


class ValidationError(MCPEngineError):
    """Error in validating parameters or return values."""


class ResourceError(MCPEngineError):
    """Error in resource operations."""


class ToolError(MCPEngineError):
    """Error in tool operations."""


class InvalidSignature(Exception):
    """Invalid signature for use with MCPEngine."""
