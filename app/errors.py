class EstimatorError(Exception):
    """Base class for domain errors that main.py maps to HTTP responses."""


class PhotosFetchError(EstimatorError):
    """The photos API (calc.duo.tax) was unreachable or returned a bad response."""


class ItemsFetchError(EstimatorError):
    """The items API (megamind) was unreachable or returned a bad response."""


class NoPhotosError(EstimatorError):
    """No usable photos were found for the given rp_id."""


class ModelError(EstimatorError):
    """The vision model call failed or returned output we could not parse."""
