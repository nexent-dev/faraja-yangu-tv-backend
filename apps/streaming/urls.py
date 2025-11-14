from django.urls import path, re_path
from . import views

app_name = 'streaming'

urlpatterns = [
    # Add your URL patterns here
    path('create-category/', views.create_category, name='create-category'),
    path('update-category/<int:pk>/', views.update_category, name='update-category'),
    path('categories/', views.get_categories, name='category-list'),
    path('categories/<int:pk>/', views.get_category, name='category-detail'),
    path('subcategories/<int:category_id>/', views.get_subcategories, name='subcategory-list'),
    path('subcategories/<int:pk>/', views.get_subcategory, name='subcategory-detail'),
    
    path('feed/', views.get_feed, name='feed-list'),
    path('get-recent-feed/', views.get_recent_feed, name='get-recent-feed-list'),
    path('search/', views.get_search, name='search-list'),
    path('get-banner-ads/', views.get_banner_ads, name='get-banner-ads-list'),
    
    path('get-all-videos/', views.get_all_videos, name='get-all-video-list'),
    path('get-videos/<int:category_id>/', views.get_videos, name='get-video-list'),
    path('get-video/<int:pk>/', views.get_video, name='get-video-detail'),
    path('get-video-comments/<int:pk>/', views.get_video_comments, name='get-video-comments-list'),
    path('get-video-related/<int:video_id>/', views.get_video_related, name='get-video-related-list'),
    
    path('create-video/', views.create_video, name='create-video'),
    path('update-video/<int:pk>/', views.update_video, name='update-video'),
    path('delete-video/<int:pk>/', views.delete_video, name='delete-video'),
    
    path('like-video/<int:video_id>/', views.like_video, name='like-video'),
    path('dislike-video/<int:video_id>/', views.dislike_video, name='dislike-video'),
    path('like-comment/<int:comment_id>/', views.like_comment, name='like-comment'),
    path('dislike-comment/<int:comment_id>/', views.dislike_comment, name='dislike-comment'),
    path('comment/<int:video_id>/', views.comment, name='comment'),
    path('reply/<int:comment_id>/', views.reply, name='reply'),
    path('view/<int:video_id>/', views.view, name='view'),
    
    # HLS Streaming endpoints
    path('stream/<int:pk>/', views.get_video_stream_url, name='get-stream-url'),
    re_path(r'^hls/(?P<video_slug>[\w-]+)/(?P<file_path>.+)$', views.stream_hls, name='stream-hls'),
]
