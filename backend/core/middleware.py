import traceback

from django.http import HttpResponse, JsonResponse


class SimpleCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS":
            response = HttpResponse()
        else:
            try:
                response = self.get_response(request)
            except Exception as error:
                traceback.print_exc()
                response = JsonResponse(
                    {"error": "SERVER_ERROR", "message": "Service is temporarily unavailable"},
                    status=500,
                )
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Headers"] = "content-type, authorization"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response
