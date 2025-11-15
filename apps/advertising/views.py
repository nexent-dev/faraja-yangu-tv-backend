from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from core.response_wrapper import success_response, error_response
from rest_framework.permissions import IsAuthenticated
from apps.advertising.models import Ad
from apps.advertising.serializers import AdSerializer

# Create your views here.

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_carousel_ads(request):
    """Return up to 4 published carousel ads, optionally filtered by ad_render_type.

    Query params:
    - ad_render_type: "CUSTOM" or "GOOGLE" (optional)
    """
    ad_render_type = request.GET.get('ad_render_type')

    qs = Ad.objects.filter(type=Ad.AD_TYPES.CAROUSEL, is_published=True)
    if ad_render_type in (Ad.AD_RENDER_TYPES.CUSTOM, Ad.AD_RENDER_TYPES.GOOGLE):
        qs = qs.filter(ad_render_type=ad_render_type)

    ads = qs.order_by('-created_at')[:4]

    serializer = AdSerializer(ads, many=True)
    return success_response(serializer.data)