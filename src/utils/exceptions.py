"""Centralized exception hierarchy."""


class AppError(Exception):
    pass


class ApiError(AppError):
    pass


class PdfError(AppError):
    pass


class LayoutError(AppError):
    pass


class PersistenceError(AppError):
    pass
