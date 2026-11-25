class IntegrationError(Exception):
    """A third-party API refused or failed. `status_code` is the HTTP code we should return."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
