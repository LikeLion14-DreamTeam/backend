from django.urls import path

from . import views

urlpatterns = [
    path("users/me/products", views.my_products, name="my-products"),
    path("products/<str:tag_id>/unlink", views.product_unlink, name="product-unlink"),
    path("products/<str:tag_id>/link", views.product_link, name="product-link"),
    ]
