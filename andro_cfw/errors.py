class AndroCFWError(Exception):
    """Base exception for andro-cfw."""


class SessionNotFoundError(AndroCFWError):
    """Raised when cfw.session cannot be found or decrypted."""


class DeploymentError(AndroCFWError):
    """Raised when the Cloudflare Worker could not be deployed."""


class ToolchainMissingError(AndroCFWError):
    """Raised when Node.js / npm / npx is not available on the system."""
