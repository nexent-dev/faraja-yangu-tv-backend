from datetime import date, timedelta
import calendar

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from core.response_wrapper import success_response, error_response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from django.utils import timezone
from django.db.models import Q, Count, Sum

from apps.authentication.models import User, Role, Devices
from apps.management.serializers import ClientSerializer, VideoAdSlotSerializer, VideoAdSlotCreateSerializer
from apps.streaming.models import VideoAdSlot, View, Like, Comment
from apps.advertising.models import Ad
from apps.analytics.models import Analytics, Report, Notification


# Create your views here.


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_summary(request):
    """Return high-level dashboard summary stats.

    Includes total and period-based (year, month, today) counts for:
    - clients (users with role USER/role id 2)
    - views (watch events)
    - watch_time (seconds)
    - likes
    - comments
    - registrations (new clients)
    - active users
    Plus aggregate metrics from advertising and analytics apps.
    """

    today = timezone.localdate()
    year_start = date(today.year, 1, 1)
    month_start = date(today.year, today.month, 1)

    # Base client queryset (role id 2 as in get_dashboard_client_stats)
    clients_qs = User.objects.filter(roles__in=[2])
    total_clients = clients_qs.count()

    # Helper to build period stats for models using created_at
    def period_counts_for_created(model_qs):
        base = model_qs
        return {
            "total": base.count(),
            "year": base.filter(created_at__date__gte=year_start).count(),
            "month": base.filter(created_at__date__gte=month_start).count(),
            "today": base.filter(created_at__date=today).count(),
        }

    # Clients / registrations use date_joined on User
    registrations = {
        "total": total_clients,
        "year": clients_qs.filter(date_joined__date__gte=year_start).count(),
        "month": clients_qs.filter(date_joined__date__gte=month_start).count(),
        "today": clients_qs.filter(date_joined__date=today).count(),
    }

    # Views, Likes, Comments restricted to client users
    views_qs = View.objects.filter(user__in=clients_qs)
    likes_qs = Like.objects.filter(user__in=clients_qs)
    comments_qs = Comment.objects.filter(user__in=clients_qs)

    views = period_counts_for_created(views_qs)
    likes = period_counts_for_created(likes_qs)
    comments = period_counts_for_created(comments_qs)

    # Active users per period (distinct viewers)
    def active_users_counts(qs):
        return {
            "total": qs.values("user").distinct().count(),
            "year": qs.filter(created_at__date__gte=year_start).values("user").distinct().count(),
            "month": qs.filter(created_at__date__gte=month_start).values("user").distinct().count(),
            "today": qs.filter(created_at__date=today).values("user").distinct().count(),
        }

    active_users = active_users_counts(views_qs)

    # Watch time (seconds) by period
    def watch_time_seconds(qs):
        agg = qs.aggregate(total=Sum("watch_time"))
        total = agg["total"]
        return int(total.total_seconds()) if total else 0

    watch_time = {
        "total": watch_time_seconds(views_qs),
        "year": watch_time_seconds(views_qs.filter(created_at__date__gte=year_start)),
        "month": watch_time_seconds(views_qs.filter(created_at__date__gte=month_start)),
        "today": watch_time_seconds(views_qs.filter(created_at__date=today)),
    }

    # Average watch time per active user (seconds)
    def safe_div(num, denom):
        return num / denom if denom else 0

    avg_watch_time_per_user = {
        "total": safe_div(watch_time["total"], active_users["total"]),
        "year": safe_div(watch_time["year"], active_users["year"]),
        "month": safe_div(watch_time["month"], active_users["month"]),
        "today": safe_div(watch_time["today"], active_users["today"]),
    }

    # Engagement rate: (likes + comments) / views
    def engagement_for_period(v, l, c):
        return safe_div(l + c, v) if v else 0

    engagement_rate = {
        "total": engagement_for_period(views["total"], likes["total"], comments["total"]),
        "year": engagement_for_period(views["year"], likes["year"], comments["year"]),
        "month": engagement_for_period(views["month"], likes["month"], comments["month"]),
        "today": engagement_for_period(views["today"], likes["today"], comments["today"]),
    }

    # Retention-style metrics based on recent activity
    last_7_start = today - timedelta(days=7)
    last_30_start = today - timedelta(days=30)

    active_last_7_days = (
        views_qs.filter(created_at__date__gte=last_7_start)
        .values("user")
        .distinct()
        .count()
    )
    active_last_30_days = (
        views_qs.filter(created_at__date__gte=last_30_start)
        .values("user")
        .distinct()
        .count()
    )

    retention = {
        "active_last_7_days": active_last_7_days,
        "active_last_30_days": active_last_30_days,
        "active_last_7_days_pct": safe_div(active_last_7_days * 100, total_clients) if total_clients else 0,
        "active_last_30_days_pct": safe_div(active_last_30_days * 100, total_clients) if total_clients else 0,
    }

    # Advertising metrics
    total_ads = Ad.objects.count()
    published_ads = Ad.objects.filter(is_published=True).count()
    ads_views_agg = Ad.objects.aggregate(total_views=Sum("views_count"), total_likes=Sum("likes_count"), total_dislikes=Sum("dislikes_count"))

    ads_metrics = {
        "total_ads": total_ads,
        "published_ads": published_ads,
        "types": {
            "banner": Ad.objects.filter(type=Ad.AD_TYPES.BANNER).count(),
            "video": Ad.objects.filter(type=Ad.AD_TYPES.VIDEO).count(),
            "carousel": Ad.objects.filter(type=Ad.AD_TYPES.CAROUSEL).count(),
        },
        "aggregates": {
            "views": ads_views_agg["total_views"] or 0,
            "likes": ads_views_agg["total_likes"] or 0,
            "dislikes": ads_views_agg["total_dislikes"] or 0,
        },
    }

    # Analytics & notifications metrics
    reports_metrics = {
        "total": Report.objects.count(),
        "pending": Report.objects.filter(status=Report.REPORT_STATUS.PENDING).count(),
        "approved": Report.objects.filter(status=Report.REPORT_STATUS.APPROVED).count(),
        "rejected": Report.objects.filter(status=Report.REPORT_STATUS.REJECTED).count(),
    }

    analytics_metrics = {
        "types": {
            "video": Analytics.objects.filter(type=Analytics.ANALYTICS_TYPES.VIDEO).count(),
            "ad": Analytics.objects.filter(type=Analytics.ANALYTICS_TYPES.AD).count(),
        }
    }

    notifications_metrics = {
        "total": Notification.objects.count(),
        "unread": Notification.objects.filter(is_read=False).count(),
    }
    
    # Device metrics
    total_devices = Devices.objects.filter(is_active=True).count()
    android_count = Devices.objects.filter(is_active=True, device_os__icontains='android').count()
    ios_count = Devices.objects.filter(is_active=True, device_os__icontains='ios').count()
    
    # Get latest app version to determine up-to-date ratio
    # Assuming higher version strings are newer (e.g., "1.0.0", "1.1.0")
    latest_version = Devices.objects.filter(is_active=True).order_by('-app_version').values_list('app_version', flat=True).first()
    
    if latest_version and total_devices > 0:
        uptodate_count = Devices.objects.filter(is_active=True, app_version=latest_version).count()
        uptodate_ratio = round((uptodate_count / total_devices) * 100, 2)
        outdated_ratio = round(100 - uptodate_ratio, 2)
    else:
        uptodate_ratio = 0
        outdated_ratio = 0
    
    devices = {
        "total": total_devices,
        "androids": android_count,
        "iOS": ios_count,
        "uptodate_ratio": uptodate_ratio,
        "outdated_ratio": outdated_ratio,
        "latest_version": latest_version or "N/A",
    }

    payload = {
        "clients": registrations,  # alias for convenience
        "registrations": registrations,
        "views": views,
        "likes": likes,
        "comments": comments,
        "watch_time": watch_time,
        "active_users": active_users,
        "avg_watch_time_per_user": avg_watch_time_per_user,
        "engagement_rate": engagement_rate,
        "retention": retention,
        "ads": ads_metrics,
        "analytics": {
            "reports": reports_metrics,
            "analytics": analytics_metrics,
            "notifications": notifications_metrics,
        },
        "devices": devices,
        "current_date": today.isoformat(),
    }

    return success_response(payload)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_client_stats(request):
    users = User.objects.filter(roles__in=[2])
    serializer = ClientSerializer(users, many=True)
    return success_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_analytics_chart(request):
    # Determine target month/year (defaults to current month in server timezone)
    today = timezone.localdate()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))

    # Compute first and last day of month
    first_day = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    last_day = date(year, month, days_in_month)

    # Base filter by created_at date range
    date_range = {"created_at__date__gte": first_day, "created_at__date__lte": last_day}

    # Aggregate Views (count + watch time) per day
    views_qs = (
        View.objects.filter(**date_range)
        .values("created_at__date")
        .annotate(count=Count("id"), watch_time_sum=Sum("watch_time"))
    )
    views_by_day = {row["created_at__date"]: row["count"] for row in views_qs}
    watch_time_by_day = {
        row["created_at__date"]: (row["watch_time_sum"].total_seconds() if row["watch_time_sum"] else 0)
        for row in views_qs
    }

    # Aggregate Likes per day
    likes_qs = (
        Like.objects.filter(**date_range)
        .values("created_at__date")
        .annotate(count=Count("id"))
    )
    likes_by_day = {row["created_at__date"]: row["count"] for row in likes_qs}

    # Aggregate Comments per day
    comments_qs = (
        Comment.objects.filter(**date_range)
        .values("created_at__date")
        .annotate(count=Count("id"))
    )
    comments_by_day = {row["created_at__date"]: row["count"] for row in comments_qs}

    # Active users per day (users with at least one view that day)
    active_qs = (
        View.objects.filter(**date_range)
        .values("created_at__date")
        .annotate(count=Count("user", distinct=True))
    )
    active_by_day = {row["created_at__date"]: row["count"] for row in active_qs}

    # Build labels (days of month) and aligned series
    labels = []
    views_series = []
    likes_series = []
    comments_series = []
    watch_time_series = []
    active_users_series = []

    for day in range(1, days_in_month + 1):
        current = date(year, month, day)
        labels.append(day)
        views_series.append(views_by_day.get(current, 0))
        likes_series.append(likes_by_day.get(current, 0))
        comments_series.append(comments_by_day.get(current, 0))
        watch_time_series.append(watch_time_by_day.get(current, 0))
        active_users_series.append(active_by_day.get(current, 0))

    # Month names for selector
    months = [
        {"id": idx, "name": name}
        for idx, name in enumerate(
            ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            start=1,
        )
    ]

    payload = {
        "current_date": today.isoformat(),
        "months": months,
        "labels": labels,
        "data": {
            "views": views_series,
            "likes": likes_series,
            "comments": comments_series,
            "watch_time": watch_time_series,
            "active_users": active_users_series,
        },
        "year": year,
        "month": month,
    }

    return success_response(payload)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_interceptor_ads(request):
    """Get all video ad slots (interceptor ads).
    
    Returns a list of all video ad slots with nested video details.
    """
    ad_slots = VideoAdSlot.objects.select_related('video').order_by('-created_at')
    serializer = VideoAdSlotSerializer(ad_slots, many=True)
    return success_response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_interceptor_ad(request):
    """Create a new video ad slot (interceptor ad).
    
    Payload:
    - video: int (video ID)
    - start_time: str (HH:MM:SS format)
    - end_time: str (HH:MM:SS format)
    """
    serializer = VideoAdSlotCreateSerializer(data=request.data)
    if serializer.is_valid():
        ad_slot = serializer.save()
        return success_response(serializer.data, message='Interceptor ad created successfully')
    
    return error_response(serializer.errors, code=400)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_interceptor_ad(request, pk):
    """Delete an interceptor ad.
    
    URL Parameters:
    - pk: int (interceptor ad ID)
    """
    try:
        ad_slot = VideoAdSlot.objects.get(pk=pk)
    except VideoAdSlot.DoesNotExist:
        return error_response('Interceptor ad not found', code=404)
    
    ad_slot.delete()
    return success_response(message='Interceptor ad deleted successfully')