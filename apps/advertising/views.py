from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from core.response_wrapper import success_response, error_response
from rest_framework.permissions import IsAuthenticated
from apps.advertising.models import Ad
from apps.advertising.serializers import AdSerializer, ClaimRewardSerializer

# Reward constants
CREDITS_PER_SECOND = 1  # Credits earned per second of ad viewing
AD_CLICK_BONUS = 10  # Bonus credits for clicking an ad

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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def claim_reward(request):
    """Claim reward credits for watching an ad.
    
    Payload:
    - time_spent_seconds: int - seconds spent watching the ad
    - ad_clicked: bool - whether the user clicked the ad
    - ad_id: int (optional) - ID of the ad watched
    
    Returns:
    - credits_earned: total credits earned from this interaction
    - new_balance: user's new credit balance
    """
    serializer = ClaimRewardSerializer(data=request.data)
    if not serializer.is_valid():
        return error_response(serializer.errors, code=400)
    
    time_spent_seconds = serializer.validated_data['time_spent_seconds']
    ad_clicked = serializer.validated_data['ad_clicked']
    ad_id = serializer.validated_data.get('ad_id')
    
    # Calculate credits
    credits_earned = time_spent_seconds * CREDITS_PER_SECOND
    if ad_clicked:
        credits_earned += AD_CLICK_BONUS
    
    # Get or create user profile
    user = request.user
    profile = user.profile
    if not profile:
        from apps.authentication.models import Profile
        profile = Profile.objects.create()
        user.profile = profile
        user.save()
    
    # Update credit accumulation
    profile.credit_accumulation += credits_earned
    profile.save()
    
    # Track ad interaction if ad_id provided
    if ad_id:
        try:
            ad = Ad.objects.get(pk=ad_id)
            profile.ads_viewed.add(ad)
            ad.views_count += 1
            if ad_clicked:
                profile.ads_clicked.add(ad)
            ad.save()
        except Ad.DoesNotExist:
            pass  # Silently ignore invalid ad_id
    
    return success_response({
        'credits_earned': credits_earned,
        'new_balance': profile.credit_accumulation,
    }, message='Reward claimed successfully')