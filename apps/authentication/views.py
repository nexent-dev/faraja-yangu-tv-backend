import random
from django.utils import timezone
from django.utils.timezone import timedelta
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.authentication.serializers.profile import ProfileSerializer
from apps.authentication.tasks.main import send_password_reset_email, send_verification_email
from core.response_wrapper import success_response, error_response
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from apps.authentication.models import OTP, User, Profile
from apps.authentication.serializers.user import UserSerializer
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
# Create your views here.

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    
    username = request.data.get('username', None)
    password = request.data.get('password', None)
    
    if not username or not password:
        return error_response(message='Username and password are required')
    
    user = authenticate(username=username, password=password)
    
    if not user:
        return error_response(message='Invalid credentials')
    
    if not user.is_active:
        return error_response(message='User is not active')
    
    if not user.is_verified:
        return error_response(message='User is not verified')
    
    # Generate JWT token pair
    refresh = RefreshToken.for_user(user)
    access_token = refresh.access_token

    response = success_response(
        data={
            'access_token': str(access_token),
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'roles': user.roles.all().values(),
            }
        },
        message='Login successful'
    )

    # Set refresh token as HTTP-only cookie
    response.set_cookie(
        'refresh_token',
        str(refresh),
        max_age=60 * 60 * 24 * 14,  # 14 days (same as REFRESH_TOKEN_LIFETIME)
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax'
    )

    return response

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_profile(request):
    
    user = User.objects.filter(id=request.user.id).first()
    
    if not user:
        return error_response(message='User not found')
    
    if user.profile:
        return error_response(message='Profile already completed')
    
    serializer = ProfileSerializer(data=request.data)
    
    if not serializer.is_valid():
        return error_response(message=serializer.errors)
    
    user.profile = serializer.save()
    user.save()
    
    return success_response(data={}, message='Profile completed successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    
    user = User.objects.filter(id=request.user.id).first()
    
    if not user:
        return error_response(message='User not found')
    
    return success_response(data={
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'roles': user.roles.all().values(),
        'profile': ProfileSerializer(user.profile).data,
    })

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_otp(request):
    
    user = User.objects.filter(id=request.user.id).first()
    
    if not user:
        return error_response(message='User not found')
    
    if not user.profile:
        return error_response(message='Profile not found')
    
    otp = OTP.objects.filter(user=user).first()
    
    if otp:
        if (timezone.now() - otp.created_at).total_seconds() < 60:
            return error_response(message='Please wait 60 seconds before resending OTP')
    
    if not otp:
        otp = OTP.objects.create(user=user)
    
    otp.otp = random.randint(100000, 999999)
    otp.expires_at = timezone.now() + timedelta(minutes=30)
    otp.save()
    
    print(otp.otp)
    
    return success_response(data={}, message='OTP sent successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_phone(request):
    
    otp = request.data.get('otp', None)
    
    if not otp:
        return error_response(message='OTP is required')
    
    user = User.objects.filter(id=request.user.id).first()
    
    if not user:
        return error_response(message='User not found')
    
    if not user.profile:
        return error_response(message='Profile not found')
    
    user.profile.is_phone_verified = True
    user.profile.save()
    
    return success_response(data={})
# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_email(request):
    
    otp = request.data.get('otp', None)
    email = request.data.get('email', None)
    
    if not email:
        return error_response(message='Email is required')
    
    if not otp:
        return error_response(message='OTP is required')
    
    user: (User, None) = User.objects.filter(email=email).first()
    
    if not user:
        return error_response(message='User not found')
    
    otp: OTP = OTP.objects.filter(user=user, otp=otp).first()
    
    if not otp:
        return error_response(message='Invalid OTP')
    
    if otp.expires_at > timezone.now():
        otp.delete()
        return error_response(message='OTP expired')
    
    user.is_verified = True
    user.save()
    otp.delete()
    
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def login_with_google(request):
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def login_google(request):
    """
    Google OAuth login endpoint.
    Accepts a Google ID token and returns JWT tokens.
    Query params: device (android/ios/web), portal (client/cms)
    """
    token = request.data.get('id_token') or request.data.get('token')
    device = request.query_params.get('device', 'web')
    portal = request.query_params.get('portal', 'client')
    
    if not token:
        return error_response(message='Google ID token is required', code=400)
    
    if not settings.GOOGLE_CLIENT_ID:
        return error_response(message='Google authentication is not configured', code=500)
    
    try:
        # Verify the Google ID token
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID
        )
        
        # Extract user info from the token
        google_id = idinfo.get('sub')
        email = idinfo.get('email')
        email_verified = idinfo.get('email_verified', False)
        first_name = idinfo.get('given_name', '')
        last_name = idinfo.get('family_name', '')
        
        if not email:
            return error_response(message='Email not provided by Google', code=400)
        
        # Check if user exists
        user = User.objects.filter(email=email).first()
        
        if user:
            # Update auth provider if needed
            if user.auth_provider != 'google':
                user.auth_provider = 'google'
                user.save()
        else:
            # Create new user
            user = User.objects.create(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                auth_provider='google',
                is_verified=email_verified,
                is_active=True,
            )
            # Create profile for new user
            profile = Profile.objects.create()
            user.profile = profile
            user.save()
        
        if not user.is_active:
            return error_response(message='User account is deactivated', code=403)
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        
        response = success_response(
            data={
                'access_token': str(access_token),
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'roles': list(user.roles.all().values()),
                    'is_new_user': not user.profile or not user.profile.id,
                },
                'device': device,
                'portal': portal,
            },
            message='Login successful'
        )
        
        # Set refresh token as HTTP-only cookie
        response.set_cookie(
            'refresh_token',
            str(refresh),
            max_age=60 * 60 * 24 * 14,  # 14 days
            httponly=True,
            secure=not settings.DEBUG,
            samesite='Lax'
        )
        
        return response
        
    except ValueError as e:
        return error_response(message='Invalid Google token', code=401)
    except Exception as e:
        return error_response(message=f'Authentication failed: {str(e)}', code=500)

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def request_verification(request):
    email = request.data.get('email')
    
    if not email:
        return error_response(message="Email is required", code=400)
    
    user = User.objects.filter(email=email).first()
    
    if not user:
        return error_response(message="There's an issue with your email make sure it's correct", code=400)
    
    if settings.DEBUG:
        send_verification_email(user.id)
    else:
        send_verification_email.delay(user.id)
    
    return success_response(data={}, message="An OTP has been sent to your email")

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    
    first_name = request.data.get('first_name', None)
    last_name = request.data.get('last_name', None)
    email = request.data.get('email', None)
    password = request.data.get('password', None)
    password_confirmation = request.data.get('password_confirmation', None)
    
    if not first_name or not last_name or not email or not password or not password_confirmation:
        return error_response(message='First name, last name, email, password and password confirmation are required')
    
    if password != password_confirmation:
        return error_response(message='Passwords do not match')
    
    if User.objects.filter(email=email).exists():
        return error_response(message='Email already exists')
    
    payload = {key: value for key, value in request.data.items() if value}
    payload['username'] = email
    payload['auth_provider'] = 'email'
    
    serializer = UserSerializer(data=payload)
    
    if not serializer.is_valid():
        return error_response(message=serializer.errors)
    
    user: User = serializer.save()

    # Set password securely
    user.set_password(password)
    user.save()

    # Ensure a profile is created and linked to this user
    if not user.profile:
        profile = Profile.objects.create()
        user.profile = profile
        user.save()

    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_user(request, id):
    
    user = User.objects.get(id=id)
    user.is_verified = True
    user.save()
    
    return success_response(data={}, message='User verified successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    
    otp_code = request.data.get('otp', None)
    
    otp = OTP.objects.filter(otp=otp_code).first()
    
    if not otp:
        return error_response(message='Invalid OTP')
    
    if otp.expires_at < timezone.now():
        return error_response(message='OTP expired')
    
    otp.delete()
    
    return success_response(data={}, message='OTP verified successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def refresh(request):
    
    refresh_token = request.COOKIES.get('refresh_token')
    
    if not refresh_token:
        return error_response(message='Refresh token is required')
    
    fcm_token = request.data.get('fcm_token')
    device_id = request.data.get('device_id')
    device_type = request.data.get('device_type')
    app_version = request.data.get('app_version')
    
    try:
        refresh = RefreshToken(refresh_token)
    except Exception as e:
        return error_response(message='Invalid refresh token')
    
    access_token = refresh.access_token
    
    user_id = refresh['user_id']
    user = User.objects.get(id=user_id)
    
    if user.devices.filter(device_id=device_id).count():
        user.devices.update(fcm_token=fcm_token, device_type=device_type, app_version=app_version)
    else:
        user.devices.create(
            device_id=device_id,
            device_type=device_type,
            app_version=app_version,
            fcm_token=fcm_token
        )
    
    response = success_response(data={
        'access_token': str(access_token),
    })
    
    response.set_cookie(
        'refresh_token',
        str(refresh),
        max_age=60 * 60 * 24 * 14,  # 14 days (same as REFRESH_TOKEN_LIFETIME)
        httponly=True,
        secure= not settings.DEBUG,
        samesite='Lax'
    )
    
    return response

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def logout(request):
    
    # Blacklist Access and Refresh Token
    refresh_token = request.COOKIES.get('refresh_token')
    
    if not refresh_token:
        return error_response(message='Refresh token is required')
    
    try:
        refresh = RefreshToken(refresh_token)
    except Exception as e:
        return error_response(message='Invalid refresh token')
    
    refresh.blacklist()
    
    response = success_response(data={}, message='Logout successful')
    
    response.delete_cookie('refresh_token')
    
    return response

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset_with_email(request):
    
    email = request.data.get('email')
    
    if not email:
        return error_response(code=400, message="Email is required")
    
    user: (User, None) = User.objects.filter(email=email).first()
    
    if not user:
        return error_response(code=400, message="There's an issue with your email")
    
    if settings.DEBUG:
        send_password_reset_email(user.id)
    else:
        send_password_reset_email.delay(user.id)
    
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset_with_phone(request):
    return success_response(data={})

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_password_reset_otp(request):
    
    otp_code = request.data.get('otp', None)
    email = request.data.get('email', None)
    
    user: (User, None) = User.objects.filter(email=email).first()
    
    otp = OTP.objects.filter(otp=otp_code, user=user).first()
        
    if not otp:
        return error_response(message='Invalid OTP')
    
    if otp.expires_at > timezone.now():
        otp.delete()
        return error_response(message='OTP expired')
    
    return success_response(data={}, message='OTP verified successfully')

# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# ////////////////////////////////////////////////////////////////////////////////////////////////// #

@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    
    otp_code = request.data.get('otp', None)
    email = request.data.get('email', None)
    password = request.data.get('password', None)
    password_confirmation = request.data.get('password_confirmation', None)
    
    # Validate required fields
    if not email:
        return error_response(message='Email is required')
    
    if not otp_code:
        return error_response(message='OTP is required')
    
    if not password:
        return error_response(message='Password is required')
    
    if not password_confirmation:
        return error_response(message='Password confirmation is required')
    
    # Check if passwords match
    if password != password_confirmation:
        return error_response(message='Passwords do not match')
    
    # Validate password strength (optional but recommended)
    if len(password) < 8:
        return error_response(message='Password must be at least 8 characters long')
    
    # Find user
    user: (User, None) = User.objects.filter(email=email).first()
    
    if not user:
        return error_response(message='User not found')
    
    # Verify OTP
    otp = OTP.objects.filter(otp=otp_code, user=user).first()
        
    if not otp:
        return error_response(message='Invalid OTP')
    
    if otp.expires_at > timezone.now():
        otp.delete()
        return error_response(message='OTP expired')
    
    # Reset password
    user.set_password(password)
    user.save()
    
    # Delete OTP after successful password reset
    otp.delete()
    
    return success_response(data={}, message='Password reset successfully')