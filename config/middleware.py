import logging

request_logger = logging.getLogger('request_logger')
error_logger = logging.getLogger('error_logger')


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_logger.info(f'{request.method} {request.get_full_path()}')

        response = self.get_response(request)

        if response.status_code >= 400:
            error_logger.warning(
                f'{request.method} {request.get_full_path()} - {response.status_code}'
            )

        return response