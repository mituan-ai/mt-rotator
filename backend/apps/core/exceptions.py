from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def problem_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and set(detail) == {"detail"}:
        detail = detail["detail"]
    title = {
        400: "请求无效",
        401: "需要登录",
        403: "没有权限",
        404: "资源不存在",
        409: "状态冲突",
        429: "请求过于频繁",
    }.get(response.status_code, "请求失败")
    code = getattr(exc, "default_code", "request_error")
    payload = {
        "type": f"https://mt-rotator.local/problems/{code}",
        "title": title,
        "status": response.status_code,
        "detail": detail if isinstance(detail, str) else title,
        "code": str(code),
    }
    if not isinstance(detail, str):
        payload["errors"] = detail
    response.data = payload
    response.content_type = "application/problem+json"
    return response


def conflict(detail: str, code: str = "conflict") -> Response:
    return Response(
        {
            "type": f"https://mt-rotator.local/problems/{code}",
            "title": "状态冲突",
            "status": status.HTTP_409_CONFLICT,
            "detail": detail,
            "code": code,
        },
        status=status.HTTP_409_CONFLICT,
        content_type="application/problem+json",
    )
