from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
import pytest

from apps.streaming.models import Video, VideoAdSlot, Category
from apps.advertising.models import Ad
from apps.authentication.models import User


@pytest.mark.django_db
class TestInterceptorAdsEndpoint:
    def setup_method(self):
        self.client = APIClient()

    def _auth_user(self):
        user = User.objects.create_user(username="testuser", password="pass1234")
        self.client.force_authenticate(user=user)
        return user

    def _create_video_with_ad(self):
        user = User.objects.create_user(username="u1", password="x")
        category = Category.objects.create(name="Cat", description="d", slug="cat")
        video = Video.objects.create(
            title="Video",
            description="desc",
            category=category,
            uploaded_by=user,
        )
        ad = Ad.objects.create(
            name="Ad1",
            type=Ad.AD_TYPES.BANNER,
            uploaded_by=user,
            is_published=True,
        )
        VideoAdSlot.objects.create(video=video, ad=ad, start_time="00:00:00", end_time="00:00:10")
        return video, ad

    def test_returns_404_when_video_not_found(self):
        self._auth_user()
        url = reverse("streaming:stream-interceptor-ads", kwargs={"video_uid": "missing"})
        response = self.client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_returns_data_null_when_no_ad_slot(self):
        user = self._auth_user()
        category = Category.objects.create(name="Cat", description="d", slug="cat")
        video = Video.objects.create(
            title="Video",
            description="desc",
            category=category,
            uploaded_by=user,
        )
        url = reverse("streaming:stream-interceptor-ads", kwargs={"video_uid": video.uid})
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"data": None}

    def test_returns_ad_payload_when_slot_exists(self):
        self._auth_user()
        video, ad = self._create_video_with_ad()
        url = reverse("streaming:stream-interceptor-ads", kwargs={"video_uid": video.uid})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["id"] == ad.id
        assert response.data["data"]["media_type"] in ("IMAGE", "VIDEO")
        assert "duration" in response.data["data"]
        assert "skippable_after" in response.data["data"]
