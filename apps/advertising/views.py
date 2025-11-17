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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_carousel_ad(request):
    data = request.data.copy()
    data['type'] = Ad.AD_TYPES.CAROUSEL
    data['uploaded_by'] = request.user.id

    serializer = AdSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data, message='Carousel ad created successfully')

    return error_response(serializer.errors, code=400)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_carousel_ad(request, pk):
    try:
        ad = Ad.objects.get(pk=pk, type=Ad.AD_TYPES.CAROUSEL)
    except Ad.DoesNotExist:
        return error_response('Carousel ad not found', code=404)

    partial = request.method == 'PATCH'
    serializer = AdSerializer(ad, data=request.data, partial=partial)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data, message='Carousel ad updated successfully')

    return error_response(serializer.errors, code=400)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_carousel_ad(request, pk):
    try:
        ad = Ad.objects.get(pk=pk, type=Ad.AD_TYPES.CAROUSEL)
    except Ad.DoesNotExist:
        return error_response('Carousel ad not found', code=404)

    ad.delete()
    return success_response(message='Carousel ad deleted successfully')