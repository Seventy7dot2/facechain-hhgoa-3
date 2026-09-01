class FaceChainError(Exception):
    """Expected, user-facing pipeline failure."""


class ConfigurationError(FaceChainError):
    """A required runtime setting is missing or invalid."""


class FaceDetectionError(FaceChainError):
    """No usable face could be detected."""


class SearchError(FaceChainError):
    """The live reverse-image search failed."""


class NoMatchError(FaceChainError):
    """No social result passed local face confirmation."""


class ChainError(FaceChainError):
    """The evidence transaction or its verification failed."""
