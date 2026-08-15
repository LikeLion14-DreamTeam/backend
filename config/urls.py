from django.contrib import admin
from django.urls import include, path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET'])
def test_connection(request):
    return Response({"message": "백엔드 연결 성공!"})

schema_view = get_schema_view(
   openapi.Info(
      title="DreamTeam API",
      default_version='v1',
      description="DreamTeam API 문서",
   ),
   public=True,
   permission_classes=[permissions.AllowAny],
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('api/test/', test_connection),
    path('', include('accounts.urls')),
    path('', include('products.urls')),
    path('', include('travel.urls')),
    path('', include('taste.urls')),
]
